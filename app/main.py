"""
RAGAgent -- retrieval + generation for one workspace.

Two changes matter here relative to the original:

* Retrieval returns *scored* chunks, and the context handed to the model is
  numbered, with an instruction to cite ``[1]``, ``[2]``.  The old prompt gave
  the model no way to attribute anything, so citations were impossible even
  when the sources were known.
* ``stream`` yields the sources first, then tokens, so a UI can render the
  citation panel while the answer is still being written.

Generation goes through the provider-neutral chat API, so a reasoning model's
thinking arrives as separate ``thinking`` events instead of leaking into the
answer, and earlier turns of a session can be passed in as history.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.index.retrieval import RetrievalResult, ScoredChunk, retrieve
from app.index.providers.type import QueryEngineType
from app.llm.main import LanguageModel, chat
from app.llm.types import (
    ChatMessage,
    Stop,
    TextDelta,
    ThinkingConfig,
    ThinkingDelta,
    Usage,
)

logger = logging.getLogger(__name__)

SYSTEM_PREAMBLE = """You are AskTheSite, answering questions strictly from the \
crawled website content provided below.

Rules:
- Use only the numbered sources. Do not rely on outside knowledge.
- Cite the sources you use inline, like [1] or [2][3], right after the claim.
- If the sources do not contain the answer, say so plainly instead of guessing.
- Be concise and concrete. Prefer specifics from the sources over generalities.
"""


@dataclass
class Answer:
    prompt: str
    answer: str
    citations: List[Dict[str, Any]]
    engine: str
    elapsed_ms: int
    model: str
    thinking: str = ""
    usage: Optional[Dict[str, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "answer": self.answer,
            "thinking": self.thinking,
            "citations": self.citations,
            "engine": self.engine,
            "elapsed_ms": self.elapsed_ms,
            "model": self.model,
            "usage": self.usage,
        }


class RAGAgent:
    """Ties a workspace's index to a language model."""

    def __init__(
        self,
        llm: LanguageModel,
        collection_name: str,
        index_version: int = 0,
        engine: str = QueryEngineType.AUTO.value,
        top_k: int = 5,
        phoenix_api_key: Optional[str] = None,
        thinking: Optional[ThinkingConfig] = None,
    ):
        if llm is None:
            raise TypeError("Missing required argument 'llm'")
        if not collection_name:
            raise TypeError("Missing required argument 'collection_name'")

        self.llm = llm
        self.collection_name = collection_name
        self.index_version = index_version
        self.engine = engine
        self.top_k = top_k
        self.thinking = thinking

        if phoenix_api_key:
            os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"api_key={phoenix_api_key}"
            logger.info("Arize Phoenix tracing enabled.")

    # ── retrieval ─────────────────────────────────────────────────────────

    def retrieve(
        self, prompt: str, engine: Optional[str] = None, top_k: Optional[int] = None
    ) -> RetrievalResult:
        return retrieve(
            self.collection_name,
            self.index_version,
            prompt,
            engine or self.engine,
            top_k or self.top_k,
        )

    # ── prompting ─────────────────────────────────────────────────────────

    @staticmethod
    def format_sources(chunks: List[ScoredChunk]) -> str:
        blocks = []
        for i, chunk in enumerate(chunks, start=1):
            label = chunk.page_title or chunk.source_url or "source"
            where = f"{label} — {chunk.heading}" if chunk.heading else label
            blocks.append(
                f"[{i}] {where}\nURL: {chunk.source_url}\n\n{chunk.content}"
            )
        return "\n\n---\n\n".join(blocks) if blocks else "(no sources found)"

    @classmethod
    def build_prompt(cls, question: str, chunks: List[ScoredChunk]) -> str:
        return (
            f"{SYSTEM_PREAMBLE}\n"
            f"=== SOURCES ===\n{cls.format_sources(chunks)}\n\n"
            f"=== QUESTION ===\n{question}\n\n"
            f"Answer (cite sources inline):"
        )

    @classmethod
    def build_messages(
        cls,
        question: str,
        chunks: List[ScoredChunk],
        history: Optional[List[ChatMessage]] = None,
    ) -> List[ChatMessage]:
        """
        System rules, then earlier turns, then this turn's sources + question.

        Sources ride on the newest user message only: earlier answers keep
        their own markers in the text, and re-sending old sources would make
        ``[1]`` ambiguous.
        """
        current = (
            f"=== SOURCES ===\n{cls.format_sources(chunks)}\n\n"
            f"=== QUESTION ===\n{question}\n\n"
            f"Answer (cite sources inline):"
        )
        return [
            ChatMessage.system(SYSTEM_PREAMBLE),
            *(history or []),
            ChatMessage.user(current),
        ]

    @staticmethod
    def citations_of(chunks: List[ScoredChunk]) -> List[Dict[str, Any]]:
        out = []
        for i, chunk in enumerate(chunks, start=1):
            payload = chunk.to_dict()
            payload["marker"] = i
            out.append(payload)
        return out

    # ── generation ────────────────────────────────────────────────────────

    def run(
        self,
        prompt: str,
        engine: Optional[str] = None,
        top_k: Optional[int] = None,
        history: Optional[List[ChatMessage]] = None,
    ) -> Answer:
        text: List[str] = []
        thought: List[str] = []
        citations: List[Dict[str, Any]] = []
        meta: Dict[str, Any] = {}
        for event, payload in self.stream(prompt, engine, top_k, history):
            if event == "sources":
                citations = payload["citations"]
                meta["engine"] = payload["engine"]
            elif event == "token":
                text.append(payload["t"])
            elif event == "thinking":
                thought.append(payload["t"])
            elif event == "done":
                meta.update(payload)
            elif event == "error":
                raise RuntimeError(payload["message"])
        return Answer(
            prompt=prompt,
            answer="".join(text),
            thinking="".join(thought),
            citations=citations,
            engine=meta.get("engine", engine or self.engine),
            elapsed_ms=meta.get("elapsed_ms", 0),
            model=meta.get("model", self.llm.model_name),
            usage=meta.get("usage"),
        )

    def stream(
        self,
        prompt: str,
        engine: Optional[str] = None,
        top_k: Optional[int] = None,
        history: Optional[List[ChatMessage]] = None,
    ) -> Iterator[Tuple[str, Any]]:
        """
        Yield ``(event, payload)`` pairs: ``sources`` first, then interleaved
        ``thinking`` and ``token`` deltas, then ``done`` -- or ``error`` if
        generation fails.
        """
        started = time.perf_counter()
        try:
            result = self.retrieve(prompt, engine, top_k)
        except Exception as exc:
            logger.exception("Retrieval failed")
            yield "error", {"message": str(exc)}
            return

        citations = self.citations_of(result.results)
        yield "sources", {
            "citations": citations,
            "engine": result.engine,
            "retrieval_ms": result.elapsed_ms,
            "error": result.error,
        }

        messages = self.build_messages(prompt, result.results, history)
        tokens = 0
        usage = Usage()
        try:
            for event in chat(self.llm, messages, thinking=self.thinking):
                if isinstance(event, TextDelta):
                    tokens += 1
                    yield "token", {"t": event.text}
                elif isinstance(event, ThinkingDelta):
                    yield "thinking", {"t": event.text}
                elif isinstance(event, Usage):
                    usage = usage + event
                elif isinstance(event, Stop):
                    break
        except Exception as exc:
            logger.exception("Generation failed")
            yield "error", {"message": str(exc)}
            return

        yield "done", {
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "model": self.llm.model_name,
            "token_count": tokens,
            "usage": usage.to_dict(),
        }
