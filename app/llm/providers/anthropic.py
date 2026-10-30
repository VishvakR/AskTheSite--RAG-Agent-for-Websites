import logging
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import anthropic

from app.llm.main import LanguageModel
from app.llm.manager import LanguageModelFactory
from app.llm.registry import ANTHROPIC_MODELS, ModelSpec
from app.llm.types import (
    ChatMessage,
    StreamEvent,
    Stop,
    TextDelta,
    ThinkingConfig,
    ThinkingDelta,
    ToolCall,
    ToolCallEvent,
    ToolSpec,
    Usage,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"

# Models the server-side refusal fallback accepts in its "default" form.
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


@LanguageModelFactory.register("anthropic")
class AnthropicModel(LanguageModel):
    """
    Claude via the official ``anthropic`` SDK.

    Native rather than LangChain because the harness needs three things the
    wrapper flattens away: streamed (summarised) thinking, tool-use blocks,
    and the raw content blocks that must be sent back unchanged inside a tool
    loop for thinking to carry over between steps.
    """

    provider = "anthropic"
    label = "Anthropic Claude"
    requires_key = True

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ):
        from app.config import get_settings

        settings = get_settings()
        self.model_name = model_name or DEFAULT_MODEL
        # Current Claude models reject sampling parameters, so temperature is
        # accepted for interface parity and deliberately not sent.
        self.temperature = temperature
        self.max_tokens = max_tokens or settings.llm_max_tokens
        self.fallbacks = settings.anthropic_fallbacks
        self.api_key = api_key or settings.anthropic_api_key
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Add it to .env or choose another provider."
            )
        self.client = anthropic.Anthropic(api_key=self.api_key)

    # ── catalogue ─────────────────────────────────────────────────────────

    @classmethod
    def status(cls, settings) -> Tuple[bool, Optional[str]]:
        if settings.anthropic_api_key:
            return True, None
        return False, "ANTHROPIC_API_KEY is not set"

    @classmethod
    def models(cls, settings) -> List[ModelSpec]:
        return list(ANTHROPIC_MODELS)

    # ── wire format ───────────────────────────────────────────────────────

    @staticmethod
    def _to_api(messages: Sequence[ChatMessage]) -> Tuple[str, List[Dict[str, Any]]]:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        out: List[Dict[str, Any]] = []

        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                if m.raw_provider == "anthropic" and m.raw:
                    out.append({"role": "assistant", "content": m.raw})
                    continue
                blocks: List[Dict[str, Any]] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                for call in m.tool_calls:
                    blocks.append(
                        {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
                    )
                if blocks:
                    out.append({"role": "assistant", "content": blocks})
            elif m.role == "tool":
                result = {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id,
                    "content": m.content,
                    "is_error": m.is_error,
                }
                # Parallel results must share one user message.
                prev = out[-1] if out else None
                if (
                    prev
                    and prev["role"] == "user"
                    and isinstance(prev["content"], list)
                    and all(b.get("type") == "tool_result" for b in prev["content"])
                ):
                    prev["content"].append(result)
                else:
                    out.append({"role": "user", "content": [result]})
        return system, out

    def _params(
        self,
        messages: Sequence[ChatMessage],
        tools: Optional[Sequence[ToolSpec]],
        thinking: Optional[ThinkingConfig],
    ) -> Dict[str, Any]:
        system, api_messages = self._to_api(messages)
        params: Dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": self.max_tokens,
            "messages": api_messages,
            # Caches the growing conversation prefix between turns.
            "cache_control": {"type": "ephemeral"},
        }
        if system:
            params["system"] = system
        if tools:
            params["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                    "eager_input_streaming": True,
                }
                for t in tools
            ]
        if thinking and thinking.enabled:
            params["thinking"] = {"type": "adaptive", "display": "summarized"}
        if thinking and thinking.effort:
            params["output_config"] = {"effort": thinking.effort}
        return params

    # ── chat ──────────────────────────────────────────────────────────────

    def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Optional[Sequence[ToolSpec]] = None,
        thinking: Optional[ThinkingConfig] = None,
    ) -> Iterator[StreamEvent]:
        params = self._params(messages, tools, thinking)
        if self.fallbacks and self.model_name in _FALLBACK_MODELS:
            stream_ctx = self.client.beta.messages.stream(
                **params, betas=[_FALLBACK_BETA], fallbacks="default"
            )
        else:
            stream_ctx = self.client.messages.stream(**params)

        with stream_ctx as stream:
            for event in stream:
                if event.type != "content_block_delta":
                    continue
                if event.delta.type == "thinking_delta" and event.delta.thinking:
                    yield ThinkingDelta(event.delta.thinking)
                elif event.delta.type == "text_delta" and event.delta.text:
                    yield TextDelta(event.delta.text)
            final = stream.get_final_message()

        text, thought, calls = [], [], []
        for block in final.content:
            if block.type == "text":
                text.append(block.text)
            elif block.type == "thinking":
                thought.append(block.thinking or "")
            elif block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else {}
                calls.append(ToolCall(id=block.id, name=block.name, arguments=args))

        # A truncated tool input parses as a valid-looking partial object;
        # never hand it to a tool.
        if final.stop_reason == "max_tokens" and calls:
            calls = []
            text.append("\n\n[Stopped: the response hit the output token limit.]")

        for call in calls:
            yield ToolCallEvent(call)

        usage = final.usage
        yield Usage(
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )

        reason = final.stop_reason or "end_turn"
        if reason == "refusal":
            details = getattr(final, "stop_details", None)
            note = getattr(details, "explanation", None) or "The model declined to answer."
            text.append(f"\n\n[{note}]")

        yield Stop(
            reason,
            ChatMessage(
                role="assistant",
                content="".join(text),
                thinking="\n\n".join(t for t in thought if t),
                tool_calls=calls,
                raw=[b.to_dict(mode="json", exclude_none=True) for b in final.content],
                raw_provider="anthropic",
            ),
        )
