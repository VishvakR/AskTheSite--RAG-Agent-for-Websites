"""
The harness: one call to :meth:`TurnRunner.run` answers one question in a
session and streams everything that happens along the way.

Two modes share the same machinery:

* ``rag``   -- retrieve once, hand the numbered sources to the model, answer.
  Works with every model, including ones that cannot call tools.
* ``agent`` -- the model drives: it searches, reads pages and lists pages as
  many times as it needs (up to ``AGENT_MAX_STEPS``), then answers.

Events (``(name, payload)`` pairs, ready to be sent as SSE):

``turn``        the turn started; ids, model, effective mode
``notice``      something the user should know (fallback to rag, compaction)
``step``        a model call began (``index``)
``thinking``    reasoning delta
``token``       answer delta -- text from a step that ends in tool calls is
                narration, not answer; the UI starts a fresh buffer each step
``tool_call``   the model asked for a tool
``tool_result`` the tool finished (preview, error flag, timing)
``sources``     the citations gathered so far this turn
``usage``       running token totals
``answer``      the final answer text and its citations
``grounding``   how much of the answer is backed by a cited source
``followups``   suggested next questions
``title``       the session was auto-titled
``done``        the turn finished; ``error`` if it failed
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from app.agent import grounding as grounding_meter
from app.agent.bridge import iterate_in_thread
from app.agent.citations import CitationLedger
from app.agent.prompts import FOLLOWUPS, STEP_LIMIT, system_prompt
from app.agent.search import citation_for, format_hit, search_workspaces
from app.agent.tools import Tool, ToolContext, ToolResult, enabled_tools
from app.catalog import SessionMode, get_catalog, new_id
from app.config import get_settings
from app.llm import (
    ChatMessage,
    LLMManager,
    Stop,
    TextDelta,
    ThinkingConfig,
    ThinkingDelta,
    ToolCall,
    ToolCallEvent,
    Usage,
    chat,
)
from app.services import sessions

logger = logging.getLogger(__name__)

Event = Tuple[str, Dict[str, Any]]


@dataclass
class TurnOptions:
    """Per-question overrides of the session's settings."""

    provider: Optional[str] = None
    model: Optional[str] = None
    mode: Optional[str] = None
    engine: Optional[str] = None
    top_k: Optional[int] = None
    thinking: Optional[Dict[str, Any]] = None
    followups: Optional[bool] = None


class TurnRunner:
    def __init__(
        self,
        session_id: str,
        prompt: str,
        options: Optional[TurnOptions] = None,
        cancel: Optional[threading.Event] = None,
        llm: Any = None,
        tools: Optional[List[Tool]] = None,
    ):
        self.session_id = session_id
        self.prompt = prompt.strip()
        self.opts = options or TurnOptions()
        self.cancel = cancel or threading.Event()
        self._llm = llm
        self._tools = tools
        self.settings = get_settings()

        self.turn_id = new_id()
        self.usage = Usage()
        self.trace: List[Dict[str, Any]] = []
        self._stop: Optional[Stop] = None
        self._partial_text: List[str] = []
        self._partial_thinking: List[str] = []

    # ── setup ─────────────────────────────────────────────────────────────

    def _workspaces(self, session) -> List[Any]:
        catalog = get_catalog()
        chosen = [catalog.get_workspace(i) for i in session.workspace_ids]
        chosen = [w for w in chosen if w is not None]
        # A chat with no sites attached searches everything that's indexed.
        return chosen or [w for w in catalog.list_workspaces() if w.chunk_count > 0]

    def _thinking(self, session) -> ThinkingConfig:
        raw = self.opts.thinking or session.thinking
        if raw is None:
            return ThinkingConfig(enabled=self.settings.llm_thinking, effort=self.settings.llm_effort)
        return ThinkingConfig.from_dict(raw)

    def _build_llm(self, provider: str, model: Optional[str]):
        if self._llm is not None:
            return self._llm
        kwargs: Dict[str, Any] = {}
        if model:
            kwargs["model_name"] = model
        return LLMManager.create(provider, **kwargs)

    # ── one model call ────────────────────────────────────────────────────

    async def _model_step(
        self, index: int, llm, messages: List[ChatMessage], tools, thinking: ThinkingConfig
    ) -> AsyncIterator[Event]:
        """Stream one assistant turn; leaves the result on ``self._stop``."""
        self._stop = None
        self._partial_text, self._partial_thinking = [], []
        started = time.perf_counter()
        step_usage = Usage()
        yield "step", {"index": index}

        specs = [t.spec() for t in tools] if tools else None
        stream = iterate_in_thread(
            lambda: chat(llm, list(messages), tools=specs, thinking=thinking), self.cancel
        )
        async for event in stream:
            if isinstance(event, TextDelta):
                self._partial_text.append(event.text)
                yield "token", {"t": event.text, "step": index}
            elif isinstance(event, ThinkingDelta):
                self._partial_thinking.append(event.text)
                yield "thinking", {"t": event.text, "step": index}
            elif isinstance(event, ToolCallEvent):
                yield "tool_call", {
                    "id": event.call.id,
                    "name": event.call.name,
                    "arguments": event.call.arguments,
                    "step": index,
                }
            elif isinstance(event, Usage):
                step_usage = step_usage + event
                self.usage = self.usage + event
                yield "usage", self.usage.to_dict()
            elif isinstance(event, Stop):
                self._stop = event

        calls = len(self._stop.message.tool_calls) if self._stop else 0
        self.trace.append({
            "step": index,
            "kind": "model",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "input_tokens": step_usage.input_tokens,
            "output_tokens": step_usage.output_tokens,
            "tool_calls": calls,
            "stop_reason": self._stop.reason if self._stop else "cancelled",
        })

    # ── tools ─────────────────────────────────────────────────────────────

    async def _run_tools(
        self, index: int, calls: List[ToolCall], tools: Dict[str, Tool], ctx: ToolContext
    ) -> List[Tuple[ToolCall, ToolResult]]:
        async def one(call: ToolCall) -> Tuple[ToolCall, ToolResult]:
            tool = tools.get(call.name)
            if tool is None:
                names = ", ".join(sorted(tools)) or "none"
                return call, ToolResult.error(f"unknown tool {call.name!r}; available: {names}")
            return call, await tool.run(ctx, call.arguments, self.settings.tool_timeout_s)

        results = await asyncio.gather(*(one(c) for c in calls))
        for call, result in results:
            self.trace.append({
                "step": index,
                "kind": "tool",
                "name": call.name,
                "elapsed_ms": result.elapsed_ms,
                "is_error": result.is_error,
            })
        return list(results)

    def _clip(self, text: str) -> str:
        limit = self.settings.tool_result_max_chars
        if len(text) <= limit:
            return text
        return text[:limit] + f"\n\n[… {len(text) - limit} more characters truncated]"

    # ── follow-ups ────────────────────────────────────────────────────────

    async def _followups(self, llm, answer: str) -> List[str]:
        messages = [
            ChatMessage.system(FOLLOWUPS),
            ChatMessage.user(f"Question: {self.prompt}\n\nAnswer: {answer[:3000]}"),
        ]
        quiet = ThinkingConfig(enabled=False, effort="low")
        text: List[str] = []

        async def collect() -> None:
            async for event in iterate_in_thread(lambda: chat(llm, messages, thinking=quiet), self.cancel):
                if isinstance(event, TextDelta):
                    text.append(event.text)
                elif isinstance(event, Usage):
                    self.usage = self.usage + event

        await asyncio.wait_for(collect(), timeout=30)
        out: List[str] = []
        for line in "".join(text).splitlines():
            line = line.strip().lstrip("-•*0123456789.) ").strip().strip('"')
            if len(line.split()) >= 3 and line not in out:
                out.append(line)
        return out[:3]

    # ── the turn ──────────────────────────────────────────────────────────

    async def run(self) -> AsyncIterator[Event]:
        if not self.prompt:
            yield "error", {"message": "Ask a question first."}
            return

        started = time.perf_counter()
        catalog = get_catalog()
        try:
            session = sessions.require(self.session_id)
        except sessions.SessionNotFound as exc:
            yield "error", {"message": str(exc)}
            return

        provider = self.opts.provider or session.provider or LLMManager.default_selection()[0]
        model = self.opts.model or (session.model if provider == session.provider else None)
        mode = self.opts.mode or session.mode
        engine = self.opts.engine or session.engine
        top_k = self.opts.top_k or session.top_k
        thinking = self._thinking(session)
        want_followups = self.settings.agent_followups if self.opts.followups is None else self.opts.followups

        try:
            llm = self._build_llm(provider, model)
        except ValueError as exc:
            yield "error", {"message": str(exc)}
            return
        spec = LLMManager.spec(provider, llm.model_name)

        if mode == SessionMode.AGENT and not spec.supports_tools:
            mode = SessionMode.RAG
            yield "notice", {
                "message": f"{llm.model_name} can't call tools, so this answer uses "
                "single-pass retrieval instead of agent mode."
            }

        if sessions.needs_compaction(session, spec.context_window):
            yield "notice", {"message": "Summarising earlier turns to fit the model's context…"}
            try:
                session = await asyncio.to_thread(sessions.compact, session, llm) or session
            except Exception:
                logger.exception("Compaction failed; continuing with full history")

        workspaces = self._workspaces(session)
        prior = [
            c
            for record in catalog.list_messages(session.id)
            if record.role == "assistant"
            for c in record.citations or []
        ]
        ledger = CitationLedger(prior)
        history = sessions.history(session)
        system = ChatMessage.system(system_prompt(mode, workspaces, session.system_prompt))

        yield "turn", {
            "turn_id": self.turn_id,
            "session_id": session.id,
            "mode": mode,
            "provider": provider,
            "model": llm.model_name,
            "workspaces": [w.id for w in workspaces],
        }

        if session.title == "New chat":
            title = sessions.title_from(self.prompt)
            catalog.update_session(session.id, title=title)
            yield "title", {"title": title}

        ctx = ToolContext(
            session=session, workspaces=workspaces, ledger=ledger,
            engine=engine, top_k=top_k, settings=self.settings,
        )

        try:
            if mode == SessionMode.AGENT:
                tools = self._tools if self._tools is not None else enabled_tools()
                messages = [system, *history, ChatMessage.user(self.prompt)]
                sessions.append(session.id, self.turn_id, ChatMessage.user(self.prompt))
                async for event in self._agent(llm, messages, tools, thinking, ctx, provider):
                    yield event
            else:
                async for event in self._rag(llm, system, history, thinking, ctx, provider, engine, top_k):
                    yield event
        except Exception as exc:
            logger.exception("Turn failed")
            yield "error", {"message": f"{exc.__class__.__name__}: {exc}"}
            return

        final = self._stop.message if self._stop else ChatMessage(
            role="assistant",
            content="".join(self._partial_text),
            thinking="".join(self._partial_thinking),
        )
        if self._stop is None or self.cancel.is_set():
            self.trace.append({"kind": "cancelled"})
            final.raw = None  # a cut-off stream has no valid native blocks
        if final.tool_calls:
            # Only reachable when the step limit was hit and the model still
            # asked for tools: keep its text, drop the unrun calls.
            final = ChatMessage(role="assistant", content=final.content, thinking=final.thinking)
        if not final.content.strip():
            final.content = "I couldn't produce an answer this time." if not self.cancel.is_set() else "(stopped)"

        citations = ledger.turn_citations()
        grounding = grounding_meter.assess(final.content, citations)
        record = sessions.append(
            session.id, self.turn_id, final,
            citations=citations, trace=self.trace, grounding=grounding,
            usage=self.usage.to_dict(), provider=provider, model=llm.model_name,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        yield "answer", {"message_id": record.id, "content": final.content, "citations": citations}
        yield "grounding", grounding

        if want_followups and not self.cancel.is_set():
            try:
                questions = await self._followups(llm, final.content)
            except Exception:
                logger.info("Follow-up suggestions failed", exc_info=True)
                questions = []
            if questions:
                catalog.update_message(record.id, followups=questions)
                yield "followups", {"questions": questions}

        totals = Usage(**(session.usage or {})) + self.usage
        catalog.update_session(session.id, usage=totals.to_dict())

        yield "done", {
            "turn_id": self.turn_id,
            "message_id": record.id,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "provider": provider,
            "model": llm.model_name,
            "mode": mode,
            "usage": self.usage.to_dict(),
            "steps": sum(1 for t in self.trace if t.get("kind") == "model"),
            "cancelled": self.cancel.is_set(),
        }

    # ── modes ─────────────────────────────────────────────────────────────

    async def _rag(
        self, llm, system: ChatMessage, history: List[ChatMessage],
        thinking: ThinkingConfig, ctx: ToolContext, provider: str, engine: str, top_k: int,
    ) -> AsyncIterator[Event]:
        started = time.perf_counter()
        ready = [w for w in ctx.workspaces if w.chunk_count > 0]
        hits, errors = await asyncio.to_thread(search_workspaces, ready, self.prompt, engine, top_k)
        blocks = []
        for ws, chunk in hits:
            citation = ctx.ledger.add(citation_for(ws, chunk))
            blocks.append(format_hit(citation["marker"], chunk))
        retrieval_ms = int((time.perf_counter() - started) * 1000)
        self.trace.append({"step": 0, "kind": "retrieve", "engine": engine, "elapsed_ms": retrieval_ms, "hits": len(hits)})

        yield "sources", {
            "citations": ctx.ledger.turn_citations(),
            "engine": engine,
            "retrieval_ms": retrieval_ms,
            "error": "; ".join(errors) or (None if ready else "No indexed sites in this chat yet."),
        }

        sources = "\n\n---\n\n".join(blocks) if blocks else "(no sources found)"
        augmented = (
            f"=== SOURCES ===\n{sources}\n\n=== QUESTION ===\n{self.prompt}\n\n"
            "Answer (cite sources inline):"
        )
        sessions.append(
            ctx.session.id, self.turn_id,
            ChatMessage(role="user", content=self.prompt, raw=augmented, raw_provider=sessions.AUGMENTED),
        )
        messages = [system, *history, ChatMessage.user(augmented)]
        async for event in self._model_step(1, llm, messages, None, thinking):
            yield event

    async def _agent(
        self, llm, messages: List[ChatMessage], tools: List[Tool],
        thinking: ThinkingConfig, ctx: ToolContext, provider: str,
    ) -> AsyncIterator[Event]:
        by_name = {t.name: t for t in tools}
        session_id = ctx.session.id

        for index in range(1, self.settings.agent_max_steps + 2):
            last_chance = index > self.settings.agent_max_steps
            if last_chance:
                note = ChatMessage(role="user", content=STEP_LIMIT, name=sessions.HARNESS_NOTE)
                sessions.append(session_id, self.turn_id, note)
                messages.append(note)
                yield "notice", {"message": "Step limit reached; asking for a final answer."}

            async for event in self._model_step(index, llm, messages, tools, thinking):
                yield event
            if self._stop is None or self.cancel.is_set():
                return

            message = self._stop.message
            if not message.tool_calls or last_chance:
                return  # final answer; persisted by run()

            sessions.append(session_id, self.turn_id, message, provider=provider, model=llm.model_name)
            messages.append(message)

            before = len(ctx.ledger)
            for call, result in await self._run_tools(index, message.tool_calls, by_name, ctx):
                content = self._clip(result.content)
                reply = ChatMessage.tool_result(call, content, result.is_error)
                sessions.append(session_id, self.turn_id, reply, elapsed_ms=result.elapsed_ms)
                messages.append(reply)
                yield "tool_result", {
                    "id": call.id,
                    "name": call.name,
                    "is_error": result.is_error,
                    "elapsed_ms": result.elapsed_ms,
                    "preview": content[:600],
                    "step": index,
                }
            if len(ctx.ledger) != before:
                yield "sources", {"citations": ctx.ledger.turn_citations(), "engine": ctx.engine}
            if self.cancel.is_set():
                return
