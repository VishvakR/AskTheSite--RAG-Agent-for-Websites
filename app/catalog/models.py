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
