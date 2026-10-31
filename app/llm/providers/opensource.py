import logging
import threading
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import ollama

from app.llm.main import LanguageModel
from app.llm.manager import LanguageModelFactory
from app.llm.registry import ModelSpec
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

_CACHE_TTL_S = 60.0
_cache_lock = threading.Lock()
_tags_cache: Dict[str, Tuple[float, List[str]]] = {}
_spec_cache: Dict[Tuple[str, str], Tuple[float, ModelSpec]] = {}


def _cached(cache: Dict, key, compute):
    now = time.monotonic()
    with _cache_lock:
        hit = cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL_S:
            return hit[1]
    value = compute()
    with _cache_lock:
        cache[key] = (now, value)
    return value


def _pulled_models(base_url: str) -> List[str]:
    def fetch() -> List[str]:
        listing = ollama.Client(host=base_url, timeout=2).list()
        return [m.model for m in listing.models]

    return _cached(_tags_cache, base_url, fetch)


def _probe_spec(base_url: str, model_id: str) -> ModelSpec:
    """Ask Ollama what a pulled model can do (``/api/show``)."""

    def fetch() -> ModelSpec:
        try:
            info = ollama.Client(host=base_url, timeout=3).show(model_id)
        except Exception:
            return ModelSpec("opensource", model_id, model_id)
        caps = set(getattr(info, "capabilities", None) or [])
        context = 8192
        for key, value in (getattr(info, "modelinfo", None) or {}).items():
            if key.endswith(".context_length") and isinstance(value, int):
                context = value
                break
        return ModelSpec(
            "opensource",
            model_id,
            model_id,
            context_window=context,
            supports_tools="tools" in caps,
            supports_thinking="thinking" in caps,
            supports_vision="vision" in caps,
        )

    return _cached(_spec_cache, (base_url, model_id), fetch)


@LanguageModelFactory.register("opensource")
class OpenSourceModel(LanguageModel):
    """
    Ollama-hosted local model -- the zero-key default that runs fully offline.

    Uses the native ``ollama`` client so reasoning arrives on its own channel
    (``think=True``) and tool calls come back structured. Models without
    native thinking still get it via the ``<think>`` tag parser.
    """

    provider = "opensource"
    label = "Ollama (local)"
    requires_key = False

    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        base_url: Optional[str] = None,
    ):
        from app.config import get_settings

        settings = get_settings()
        self.model_name = model_name or settings.llm_model
        self.temperature = settings.llm_temperature if temperature is None else temperature
        # Previously hardcoded to Ollama's localhost default, which breaks in Docker.
        self.base_url = base_url or settings.ollama_base_url
        self.client = ollama.Client(host=self.base_url)

    # ── catalogue ─────────────────────────────────────────────────────────

    @classmethod
    def status(cls, settings) -> Tuple[bool, Optional[str]]:
        try:
            pulled = _pulled_models(settings.ollama_base_url)
        except Exception as exc:
            return False, (
                f"Ollama unreachable at {settings.ollama_base_url} ({exc.__class__.__name__})"
            )
        if not pulled:
            return False, "Ollama is running but no models are pulled (try: ollama pull qwen3:8b)"
        return True, None

    @classmethod
    def models(cls, settings) -> List[ModelSpec]:
        try:
            pulled = _pulled_models(settings.ollama_base_url)
        except Exception:
            return []
        return [_probe_spec(settings.ollama_base_url, m) for m in pulled]

    @classmethod
    def default_model(cls, settings) -> str:
        return settings.llm_model

    @classmethod
    def spec_for(cls, model_id: str, settings: Any = None) -> ModelSpec:
        if settings is None:
            from app.config import get_settings

            settings = get_settings()
        return _probe_spec(settings.ollama_base_url, model_id)

    # ── wire format ───────────────────────────────────────────────────────

    @staticmethod
    def _to_api(messages: Sequence[ChatMessage]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for m in messages:
            if m.role == "tool":
                out.append({"role": "tool", "content": m.content, "tool_name": m.name})
            elif m.role == "assistant":
                entry: Dict[str, Any] = {"role": "assistant", "content": m.content}
                if m.tool_calls:
                    entry["tool_calls"] = [
                        {"function": {"name": c.name, "arguments": c.arguments}}
                        for c in m.tool_calls
                    ]
                out.append(entry)
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    # ── chat ──────────────────────────────────────────────────────────────

    def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Optional[Sequence[ToolSpec]] = None,
        thinking: Optional[ThinkingConfig] = None,
    ) -> Iterator[StreamEvent]:
        spec = self.spec
        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": self._to_api(messages),
            "stream": True,
            "options": {"temperature": self.temperature},
        }
        # Ollama rejects tools/think for models that lack the capability.
        if tools and spec.supports_tools:
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
        if spec.supports_thinking:
            enabled = thinking.enabled if thinking else True
            effort = thinking.effort if thinking else None
            kwargs["think"] = (effort or True) if enabled else False

        parser = ThinkTagParser()
        text: List[str] = []
        thought: List[str] = []
        calls: List[ToolCall] = []
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

        for chunk in self.client.chat(**kwargs):
            msg = chunk.message
            if msg.thinking:
                thought.append(msg.thinking)
                yield ThinkingDelta(msg.thinking)
            if msg.content:
                yield from route(parser.feed(msg.content))
            for tc in msg.tool_calls or []:
                calls.append(
                    ToolCall(
                        id=f"call_{uuid.uuid4().hex[:12]}",
                        name=tc.function.name,
                        arguments=dict(tc.function.arguments or {}),
                    )
                )
            if chunk.done:
                usage = Usage(chunk.prompt_eval_count or 0, chunk.eval_count or 0)
                reason = chunk.done_reason or reason
        yield from route(parser.flush())

        for call in calls:
            yield ToolCallEvent(call)
        yield usage
        yield Stop(
            "tool_use" if calls else reason,
            ChatMessage(
                role="assistant",
                content="".join(text),
                thinking="".join(thought),
                tool_calls=calls,
            ),
        )
