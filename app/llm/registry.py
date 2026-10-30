"""
What each model can do.

The harness asks this before every turn: tools are only offered to models that
support tool calling, thinking is only requested from models that can do it,
and the context window decides how much history fits. Models that are not
listed here still work -- they get conservative defaults for their provider.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    id: str
    label: str = ""
    context_window: int = 8192
    supports_tools: bool = False
    supports_thinking: bool = False
    supports_vision: bool = False
    description: str = ""

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.id}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self) | {"label": self.label or self.id, "key": self.key}


ANTHROPIC_MODELS = [
    ModelSpec(
        "anthropic", "claude-opus-5-5", "Claude Opus 5.5", 1_000_000, True, True, True,
        "Most capable Opus. Best for multi-step research across pages.",
    ),
    ModelSpec(
        "anthropic", "claude-sonnet-5-5", "Claude Sonnet 5.5", 1_000_000, True, True, True,
        "Fast and strong for everyday questions.",
    ),
    ModelSpec(
        "anthropic", "claude-haiku-5-5", "Claude Haiku 5.5", 1_000_000, True, True, True,
        "Cheapest and quickest; good for simple lookups.",
    ),
]

OPENAI_MODELS = [
    ModelSpec("openai", "gpt-4.1", "GPT-4.1", 1_000_000, True, False, True),
    ModelSpec("openai", "gpt-4.1-mini", "GPT-4.1 mini", 1_000_000, True, False, True),
    ModelSpec("openai", "gpt-4o-mini", "GPT-4o mini", 128_000, True, False, True),
]

# What we assume about a model nobody has described.
_PROVIDER_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "anthropic": {"context_window": 200_000, "supports_tools": True, "supports_thinking": True},
    "openai": {"context_window": 128_000, "supports_tools": True},
    "openai_compatible": {"context_window": 32_768, "supports_tools": True},
    "opensource": {"context_window": 8192},
}


def fallback_spec(provider: str, model_id: str) -> ModelSpec:
    return ModelSpec(provider, model_id, model_id, **_PROVIDER_DEFAULTS.get(provider, {}))
