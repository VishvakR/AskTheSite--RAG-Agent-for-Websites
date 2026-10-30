"""Language-model abstraction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Iterator, List, Optional, Sequence, Tuple

from .thinking import ThinkTagParser
from .types import (
    ChatMessage,
    StreamEvent,
    Stop,
    TextDelta,
    ThinkingConfig,
    ThinkingDelta,
    ToolSpec,
)

if TYPE_CHECKING:
    from .registry import ModelSpec


class LanguageModel:
    """
    Base class for every LLM provider.

    A provider implements either :meth:`chat` (structured messages, tools and
    thinking -- what the agent harness uses) or :meth:`generate_response` (a
    plain prompt in, text out). Whichever one it implements, the other entry
    points fall back to it, so a minimal provider still works everywhere --
    it just won't be offered tools.
    """

    #: Registry key, set by subclasses.
    provider: str = "unknown"
    model_name: str = ""

    #: Shown in model pickers.
    label: ClassVar[str] = ""
    requires_key: ClassVar[bool] = False

    # ── single-prompt API ─────────────────────────────────────────────────

    def generate_response(self, prompt: str) -> str:
        """Return the complete answer for *prompt*."""
        text = []
        for event in self.chat([ChatMessage.user(prompt)]):
            if isinstance(event, TextDelta):
                text.append(event.text)
        return "".join(text)

    def stream_response(self, prompt: str) -> Iterator[str]:
        """Yield the answer in pieces. Default: one piece."""
        yield self.generate_response(prompt)

    # ── structured chat API ───────────────────────────────────────────────

    def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Optional[Sequence[ToolSpec]] = None,
        thinking: Optional[ThinkingConfig] = None,
    ) -> Iterator[StreamEvent]:
        """
        Stream one assistant turn as :mod:`app.llm.types` events, ending with
        a :class:`Stop`. The default flattens the conversation into a prompt
        and ignores *tools*.
        """
        if type(self).generate_response is LanguageModel.generate_response and (
            type(self).stream_response is LanguageModel.stream_response
        ):
            raise NotImplementedError(
                f"{type(self).__name__} must implement chat() or generate_response()"
            )
        return chat_via_prompt(self, messages)

    # ── catalogue hooks (classmethods: no instance, no API key needed) ────

    @classmethod
    def status(cls, settings: Any) -> Tuple[bool, Optional[str]]:
        """Is this provider usable right now, and if not, why not?"""
        return True, None

    @classmethod
    def models(cls, settings: Any) -> List["ModelSpec"]:
        """Models worth offering in a picker. Unlisted ids still work."""
        return []

    @classmethod
    def default_model(cls, settings: Any) -> str:
        listed = cls.models(settings)
        return listed[0].id if listed else ""

    @classmethod
    def spec_for(cls, model_id: str, settings: Any = None) -> "ModelSpec":
        from .registry import fallback_spec

        for spec in cls.models(settings) if settings is not None else []:
            if spec.id == model_id:
                return spec
        return fallback_spec(cls.provider, model_id)

    @property
    def spec(self) -> "ModelSpec":
        from app.config import get_settings

        return type(self).spec_for(self.model_name, get_settings())

    def describe(self) -> dict:
        return {"provider": self.provider, "model": self.model_name}


# ── helpers usable with any provider, including duck-typed ones ───────────


def render_prompt(messages: Sequence[ChatMessage]) -> str:
    """Flatten a conversation into one prompt for text-only providers."""
    system = [m.content for m in messages if m.role == "system"]
    turns = []
    for m in messages:
        if m.role == "user":
            turns.append(f"User: {m.content}")
        elif m.role == "assistant" and m.content:
            turns.append(f"Assistant: {m.content}")
        elif m.role == "tool":
            turns.append(f"Tool result ({m.name}): {m.content}")
    head = "\n\n".join(system)
    body = "\n\n".join(turns)
    return f"{head}\n\n{body}\n\nAssistant:" if head else f"{body}\n\nAssistant:"


def chat_via_prompt(llm: Any, messages: Sequence[ChatMessage]) -> Iterator[StreamEvent]:
    """
    Drive a text-only provider through the chat contract. Inline ``<think>``
    tags are still split out, so reasoning models get a thinking channel even
    without native support.
    """
    parser = ThinkTagParser()
    text: List[str] = []
    thought: List[str] = []

    def route(segments):
        for kind, piece in segments:
            if kind == "thinking":
                thought.append(piece)
                yield ThinkingDelta(piece)
            else:
                text.append(piece)
                yield TextDelta(piece)

    for piece in llm.stream_response(render_prompt(messages)):
        yield from route(parser.feed(piece))
    yield from route(parser.flush())

    yield Stop(
        "end_turn",
        ChatMessage(role="assistant", content="".join(text), thinking="".join(thought)),
    )


def chat(
    llm: Any,
    messages: Sequence[ChatMessage],
    tools: Optional[Sequence[ToolSpec]] = None,
    thinking: Optional[ThinkingConfig] = None,
) -> Iterator[StreamEvent]:
    """Call ``llm.chat`` if the object has one, else adapt its prompt API."""
    if hasattr(llm, "chat"):
        return llm.chat(messages, tools=tools, thinking=thinking)
    return chat_via_prompt(llm, messages)
