"""
Widgets for the chat log.

A :class:`TurnView` is one question and everything produced for it. Each
model call in the turn gets a :class:`StepView`: its reasoning (collapsed),
its text, and the tools it called. Text from a step that went on to call tools
is narration ("Let me search…"), so it's dimmed; the last step's text is the
answer.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Collapsible, Markdown, Static


def _short(value: Any, limit: int = 60) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_args(arguments: Dict[str, Any]) -> str:
    return " ".join(f"{k}={_short(v, 40)}" for k, v in arguments.items() if v not in (None, ""))


def format_tokens(usage: Optional[Dict[str, int]]) -> str:
    if not usage:
        return ""
    total = (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
    return f"{total / 1000:.1f}k tok" if total >= 1000 else f"{total} tok"


def grounding_label(grounding: Optional[Dict[str, Any]]) -> str:
    if not grounding or grounding.get("score") is None:
        return ""
    pct = round(grounding["score"] * 100)
    colour = {"grounded": "green", "partly grounded": "yellow"}.get(grounding["label"], "red")
    return f"[{colour}]● {grounding['label']} {pct}%[/]"


class ThinkingBlock(Collapsible):
    """Reasoning, collapsed by default; the title shows how long it took."""

    def __init__(self, text: str = "", live: bool = False) -> None:
        self._text = text
        self._started = time.monotonic()
        self._body = Static(escape(text), classes="thinking-text")
        super().__init__(self._body, title="Thinking…" if live else "Thought", collapsed=True, classes="thinking")

    def append(self, piece: str) -> None:
        self._text += piece
        self._body.update(escape(self._text))

    def finish(self) -> None:
        seconds = time.monotonic() - self._started
        self.title = f"Thought for {seconds:.1f}s"


class ToolCallBlock(Static):
    """One tool call: name and arguments, then its outcome once it lands."""

    def __init__(self, call_id: str, name: str, arguments: Dict[str, Any]) -> None:
        self.call_id = call_id
        self.tool_name = name
        self.arguments = arguments
        super().__init__(self._markup(None), classes="tool-call")

    def _markup(self, result: Optional[Dict[str, Any]]) -> str:
        head = f"[b]⚙ {escape(self.tool_name)}[/b] [dim]{escape(format_args(self.arguments))}[/]"
        if result is None:
            return f"{head}  [dim italic]running…[/]"
        if result.get("is_error"):
            return f"{head}  [red]✗ {escape(_short(result.get('preview') or result.get('result') or 'failed', 80))}[/]"
        ms = result.get("elapsed_ms")
        timing = f" {ms}ms" if ms is not None else ""
        return f"{head}  [green]✓[/][dim]{timing}[/]"

    def resolve(self, result: Dict[str, Any]) -> None:
        self.update(self._markup(result))


class StepView(Vertical):
    def __init__(self, index: int) -> None:
        super().__init__(classes="step")
        self.index = index
        self.thinking: Optional[ThinkingBlock] = None
        self.text = Markdown("", classes="step-text")
        self._stream = None
        self._buffer = ""
        self.tools: Dict[str, ToolCallBlock] = {}

    def compose(self) -> ComposeResult:
        yield self.text

    async def add_thinking(self, piece: str) -> None:
        if self.thinking is None:
            self.thinking = ThinkingBlock(live=True)
            await self.mount(self.thinking, before=self.text)
        self.thinking.append(piece)

    async def add_text(self, piece: str) -> None:
        if self._stream is None:
            self._stream = Markdown.get_stream(self.text)
        self._buffer += piece
        await self._stream.write(piece)

    async def add_tool(self, call_id: str, name: str, arguments: Dict[str, Any]) -> None:
        block = ToolCallBlock(call_id, name, arguments)
        self.tools[call_id] = block
        await self.mount(block)
        # Text before a tool call was the model thinking aloud, not the answer.
        self.text.add_class("narration")

    async def finish(self) -> None:
        if self._stream is not None:
            await self._stream.stop()
            self._stream = None
        if self.thinking is not None:
            self.thinking.finish()
        if not self._buffer.strip():
            self.text.display = False


class FollowUp(Button):
    class Picked(Message):
        def __init__(self, question: str) -> None:
            super().__init__()
            self.question = question

    def __init__(self, question: str) -> None:
        super().__init__(f"→ {question}", classes="followup", compact=True)
        self.question = question

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.post_message(self.Picked(self.question))


class TurnView(Vertical):
    """One question and its answer, live or loaded from history."""

    def __init__(self, question: str, turn_id: Optional[str] = None) -> None:
        super().__init__(classes="turn")
        self.question = question
        self.turn_id = turn_id
        self.steps: List[StepView] = []
        self.notices = Vertical(classes="notices")
        self.meta = Static("", classes="meta")
        self.followups = Horizontal(classes="followups")
        self.answer: Optional[Dict[str, Any]] = None

    def compose(self) -> ComposeResult:
        yield Static(escape(self.question), classes="user")
        yield self.notices
        yield self.meta
        yield self.followups

    # ── live updates ──────────────────────────────────────────────────────

    async def start_step(self, index: int) -> StepView:
        if self.steps:
            await self.steps[-1].finish()
        step = StepView(index)
        self.steps.append(step)
        await self.mount(step, before=self.meta)
        return step

    def current_step(self) -> Optional[StepView]:
        return self.steps[-1] if self.steps else None

    async def notice(self, text: str, error: bool = False) -> None:
        await self.notices.mount(Static(escape(text), classes="error" if error else "notice"))

    def tool_block(self, call_id: str) -> Optional[ToolCallBlock]:
        for step in reversed(self.steps):
            if call_id in step.tools:
                return step.tools[call_id]
        return None

    async def finish(self) -> None:
        if self.steps:
            await self.steps[-1].finish()

    def set_meta(self, parts: List[str]) -> None:
        self.meta.update("  ·  ".join(p for p in parts if p))

    async def set_followups(self, questions: List[str]) -> None:
        await self.followups.remove_children()
        if questions:
            await self.followups.mount_all(FollowUp(q) for q in questions)

    # ── history ───────────────────────────────────────────────────────────

    async def load(self, turn: Dict[str, Any]) -> None:
        """Render a stored turn (from ``sessions.turns``) in one go."""
        answer = turn.get("answer") or {}
        self.answer = answer or None
        step = await self.start_step(0)
        if answer.get("thinking"):
            step.thinking = ThinkingBlock(answer["thinking"])
            await step.mount(step.thinking, before=step.text)
        for s in turn.get("steps", []):
            block = ToolCallBlock(s["id"], s["name"], s.get("arguments") or {})
            block.resolve(s)
            step.tools[s["id"]] = block
            await step.mount(block, before=step.text)
        await step.text.update(answer.get("content") or "_No answer was saved for this turn._")
        self.set_meta([
            answer.get("model") or "",
            f"{answer['elapsed_ms'] / 1000:.1f}s" if answer.get("elapsed_ms") else "",
            format_tokens(answer.get("usage")),
            grounding_label(answer.get("grounding")),
        ])
        await self.set_followups(answer.get("followups") or [])
