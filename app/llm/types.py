"""
Provider-neutral chat types.

Every provider translates its own wire format into these, so the agent loop,
the session store and the UIs only ever deal with one shape: messages going
in, a stream of small events coming out.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional, Union

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolSpec:
    """What a model is told about a tool: a name, a purpose and a JSON schema."""

    name: str
    description: str
    input_schema: Dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolCall":
        return cls(id=data["id"], name=data["name"], arguments=data.get("arguments") or {})


@dataclass
class ChatMessage:
    role: Role
    content: str = ""
    thinking: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    # role == "tool" only: which call this answers, and whether it failed.
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    is_error: bool = False
    # Provider-native assistant content, replayed verbatim on the next request.
    # Anthropic needs its signed thinking blocks back unchanged inside a tool
    # loop; other providers ignore this.
    raw: Any = None
    raw_provider: Optional[str] = None

    @classmethod
    def system(cls, text: str) -> "ChatMessage":
        return cls(role="system", content=text)

    @classmethod
    def user(cls, text: str) -> "ChatMessage":
        return cls(role="user", content=text)

    @classmethod
    def tool_result(
        cls, call: ToolCall, content: str, is_error: bool = False
    ) -> "ChatMessage":
        return cls(
            role="tool",
            content=content,
            tool_call_id=call.id,
            name=call.name,
            is_error=is_error,
        )


@dataclass
class ThinkingConfig:
    """
    ``enabled`` asks for visible reasoning; ``effort`` is a hint for how hard
    to think (``low`` | ``medium`` | ``high``). Providers map these onto
    whatever their API supports and ignore what it doesn't.
    """

    enabled: bool = True
    effort: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ThinkingConfig":
        data = data or {}
        return cls(enabled=bool(data.get("enabled", True)), effort=data.get("effort"))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── stream events ─────────────────────────────────────────────────────────


@dataclass
class TextDelta:
    text: str


@dataclass
class ThinkingDelta:
    text: str


@dataclass
class ToolCallEvent:
    call: ToolCall


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
        )

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


@dataclass
class Stop:
    """Always the last event: why the model stopped, and the assembled turn."""

    reason: str
    message: ChatMessage


StreamEvent = Union[TextDelta, ThinkingDelta, ToolCallEvent, Usage, Stop]
