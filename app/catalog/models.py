"""Dataclasses mirroring the catalog tables."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utcnow() -> str:
    """ISO-8601 UTC timestamp, second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WorkspaceStatus:
    EMPTY = "empty"
    CRAWLING = "crawling"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    TERMINAL = {SUCCEEDED, FAILED, CANCELLED}


class JobKind:
    CRAWL = "crawl"
    INGEST = "ingest"
    FULL = "full"


@dataclass
class Workspace:
    id: str
    name: str
    seed_url: str
    mode: str = "page"
    status: str = WorkspaceStatus.EMPTY
    page_count: int = 0
    chunk_count: int = 0
    index_version: int = 0
    max_pages: int = 100
    max_depth: int = 3
    error: Optional[str] = None
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)

    @property
    def collection_name(self) -> str:
        """Chroma collection backing this workspace."""
        return f"ws_{self.id}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self) | {"collection_name": self.collection_name}


@dataclass
class Job:
    id: str
    workspace_id: str
    kind: str
    status: str = JobStatus.QUEUED
    phase: str = ""
    current: int = 0
    total: int = 0
    message: str = ""
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=utcnow)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    @property
    def is_terminal(self) -> bool:
        return self.status in JobStatus.TERMINAL

    @property
    def percent(self) -> Optional[float]:
        if not self.total:
            return None
        return round(100.0 * self.current / self.total, 1)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self) | {"percent": self.percent}


@dataclass
class QueryRecord:
    id: str
    workspace_id: str
    prompt: str
    engine: str
    top_k: int
    answer: Optional[str] = None
    citations: Optional[List[Dict[str, Any]]] = None
    elapsed_ms: Optional[int] = None
    created_at: str = field(default_factory=utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def dumps(value: Any) -> Optional[str]:
    return None if value is None else json.dumps(value)


def loads(value: Optional[str]) -> Any:
    return None if not value else json.loads(value)


class SessionMode:
    RAG = "rag"        # retrieve once, then answer
    AGENT = "agent"    # model drives tools in a loop

    ALL = {RAG, AGENT}


@dataclass
class Session:
    """A conversation, optionally scoped to one or more workspaces."""

    id: str
    title: str = "New chat"
    workspace_ids: List[str] = field(default_factory=list)
    provider: Optional[str] = None
    model: Optional[str] = None
    mode: str = SessionMode.RAG
    engine: str = "auto"
    top_k: int = 5
    thinking: Optional[Dict[str, Any]] = None
    system_prompt: Optional[str] = None
    pinned: bool = False
    # Rolling summary of turns that no longer fit the model's context window.
    summary: Optional[str] = None
    summary_upto: int = 0
    usage: Optional[Dict[str, int]] = None
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)

    JSON_FIELDS = ("workspace_ids", "thinking", "usage")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MessageRecord:
    """
    One chat message exactly as the model saw it.

    Every step of an agent run is stored -- the assistant's tool calls and
    each tool result -- so history replays verbatim. ``turn_id`` groups a user
    message with everything produced in answer to it.
    """

    id: str
    session_id: str
    turn_id: str
    seq: int
    role: str
    content: str = ""
    thinking: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None
    is_error: bool = False
    raw: Optional[Any] = None
    raw_provider: Optional[str] = None
    citations: Optional[List[Dict[str, Any]]] = None
    trace: Optional[List[Dict[str, Any]]] = None
    grounding: Optional[Dict[str, Any]] = None
    followups: Optional[List[str]] = None
    usage: Optional[Dict[str, int]] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    elapsed_ms: Optional[int] = None
    feedback: int = 0
    created_at: str = field(default_factory=utcnow)

    JSON_FIELDS = (
        "tool_calls", "raw", "citations", "trace", "grounding", "followups", "usage",
    )

    def to_dict(self, include_raw: bool = False) -> Dict[str, Any]:
        data = asdict(self)
        if not include_raw:
            data.pop("raw", None)
        return data


@dataclass
class ModelSetting:
    """Per-model switches the user controls from the UI."""

    provider: str
    model_id: str
    enabled: bool = True
    is_default: bool = False
    params: Optional[Dict[str, Any]] = None
    updated_at: str = field(default_factory=utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MCPServerConfig:
    """An external MCP server whose tools the agent may call."""

    id: str
    name: str
    transport: str = "stdio"  # stdio | http
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)

    JSON_FIELDS = ("args", "env", "headers")

    def to_dict(self, redact: bool = True) -> Dict[str, Any]:
        data = asdict(self)
        if redact:
            # Values often carry tokens; names are enough for a UI.
            data["env"] = {k: "•••" for k in self.env}
            data["headers"] = {k: "•••" for k in self.headers}
        return data
