import json
import logging
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from openai import OpenAI

from app.llm.main import LanguageModel
from app.llm.manager import LanguageModelFactory
from app.llm.registry import OPENAI_MODELS, ModelSpec, fallback_spec
from app.llm.thinking import ThinkTagParser
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

# Reasoning models reject a custom temperature.
_NO_TEMPERATURE_PREFIXES = ("o1", "o3", "o4", "gpt-5")


class _ChatCompletionsModel(LanguageModel):
    """
    Shared Chat Completions streaming for OpenAI and every server that speaks
    its protocol (LM Studio, vLLM, OpenRouter, Groq, …).

    Reasoning shows up in different places depending on the server:
    ``reasoning_content`` / ``reasoning`` deltas, or ``<think>`` tags inline in
    the content. All three are routed to the thinking channel.
    """

    def __init__(self, model_name: str, temperature: Optional[float], api_key: str, base_url: Optional[str]):
        from app.config import get_settings

        settings = get_settings()
        self.model_name = model_name
        self.temperature = settings.llm_temperature if temperature is None else temperature
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    @staticmethod
    def _to_api(messages: Sequence[ChatMessage]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for m in messages:
            if m.role == "tool":
                out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
            elif m.role == "assistant":
                entry: Dict[str, Any] = {"role": "assistant", "content": m.content or None}
                if m.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                        }
                        for c in m.tool_calls
                    ]
                out.append(entry)
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Optional[Sequence[ToolSpec]] = None,
        thinking: Optional[ThinkingConfig] = None,
    ) -> Iterator[StreamEvent]:
        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": self._to_api(messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if not self.model_name.startswith(_NO_TEMPERATURE_PREFIXES):
            kwargs["temperature"] = self.temperature
        if tools and self.spec.supports_tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]

        parser = ThinkTagParser()
        text: List[str] = []
        thought: List[str] = []
        partial: Dict[int, Dict[str, str]] = {}
        usage = Usage()
        reason = "end_turn"

        def route(segments):
            for kind, piece in segments:
                if kind == "thinking":
                    thought.append(piece)
                    yield ThinkingDelta(piece)
                else:
                    text.append(piece)
                    yield TextDelta(piece)

        for chunk in self.client.chat.completions.create(**kwargs):
            if chunk.usage:
                usage = Usage(chunk.usage.prompt_tokens or 0, chunk.usage.completion_tokens or 0)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            extra = getattr(delta, "model_extra", None) or {}
            reasoning = extra.get("reasoning_content") or extra.get("reasoning")
            if isinstance(reasoning, str) and reasoning:
                thought.append(reasoning)
                yield ThinkingDelta(reasoning)
            if delta.content:
                yield from route(parser.feed(delta.content))
            for tc in delta.tool_calls or []:
                slot = partial.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] += tc.function.name
                if tc.function and tc.function.arguments:
                    slot["args"] += tc.function.arguments
            if choice.finish_reason:
                reason = choice.finish_reason
        yield from route(parser.flush())

        calls: List[ToolCall] = []
        for index in sorted(partial):
            slot = partial[index]
            try:
                args = json.loads(slot["args"] or "{}")
            except json.JSONDecodeError:
                # Let the harness report it back to the model as a tool error.
                args = {"__invalid_json__": slot["args"]}
            calls.append(ToolCall(id=slot["id"] or f"call_{index}", name=slot["name"], arguments=args))

        for call in calls:
            yield ToolCallEvent(call)
        yield usage
        yield Stop(
            "tool_use" if calls else ("max_tokens" if reason == "length" else "end_turn"),
            ChatMessage(
                role="assistant",
                content="".join(text),
                thinking="".join(thought),
                tool_calls=calls,
            ),
        )


@LanguageModelFactory.register("openai")
class OpenAIModel(_ChatCompletionsModel):
    """OpenAI's hosted models."""

    provider = "openai"
    label = "OpenAI"
    requires_key = True

    def __init__(
        self,
        model_name: str = "gpt-4.1-mini",
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
    ):
        from app.config import get_settings

        key = api_key or get_settings().openai_api_key
        if not key:
            raise ValueError(
                "OPENAI_API_KEY is not set. Add it to .env or choose another provider."
            )
        super().__init__(model_name or "gpt-4.1-mini", temperature, key, None)

    @classmethod
    def status(cls, settings) -> Tuple[bool, Optional[str]]:
        if settings.openai_api_key:
            return True, None
        return False, "OPENAI_API_KEY is not set"

    @classmethod
    def models(cls, settings) -> List[ModelSpec]:
        return list(OPENAI_MODELS)


@LanguageModelFactory.register("openai_compatible")
class OpenAICompatibleModel(_ChatCompletionsModel):
    """
    Any OpenAI-compatible endpoint: LM Studio, vLLM, llama.cpp server,
    OpenRouter, Groq, Together… Point ``OPENAI_COMPATIBLE_BASE_URL`` at it and
    every model it serves becomes selectable without writing a provider.
    """

    provider = "openai_compatible"
    label = "OpenAI-compatible"
    requires_key = False

    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        from app.config import get_settings

        settings = get_settings()
        base = base_url or settings.openai_compatible_base_url
        if not base:
            raise ValueError(
                "OPENAI_COMPATIBLE_BASE_URL is not set. Point it at an OpenAI-compatible "
                "server (e.g. http://localhost:1234/v1 for LM Studio)."
            )
        model = model_name or type(self).default_model(settings)
        if not model:
            raise ValueError("No model given and OPENAI_COMPATIBLE_MODELS is empty.")
        # Local servers ignore the key but the client insists on one.
        key = api_key or settings.openai_compatible_api_key or "not-needed"
        super().__init__(model, temperature, key, base)

    @classmethod
    def status(cls, settings) -> Tuple[bool, Optional[str]]:
        if not settings.openai_compatible_base_url:
            return False, "OPENAI_COMPATIBLE_BASE_URL is not set"
        if not cls.models(settings):
            return False, f"No models listed at {settings.openai_compatible_base_url}"
        return True, None

    @classmethod
    def models(cls, settings) -> List[ModelSpec]:
        if not settings.openai_compatible_base_url:
            return []
        ids = list(settings.openai_compatible_models)
        if not ids:
            try:
                client = OpenAI(
                    api_key=settings.openai_compatible_api_key or "not-needed",
                    base_url=settings.openai_compatible_base_url,
                    timeout=2,
                    max_retries=0,
                )
                ids = [m.id for m in client.models.list()]
            except Exception as exc:
                logger.debug("Could not list OpenAI-compatible models: %s", exc)
                return []
        return [fallback_spec(cls.provider, i) for i in ids]
