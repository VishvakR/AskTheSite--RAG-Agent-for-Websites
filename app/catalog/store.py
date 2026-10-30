"""
Thread-safe SQLite catalog.

FastAPI runs sync ``def`` routes in a threadpool and the job runner touches the
catalog from worker threads, so every statement goes through one connection
opened with ``check_same_thread=False`` and guarded by a re-entrant lock.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.catalog.models import (
    Job,
    JobStatus,
    QueryRecord,
    Workspace,
    WorkspaceStatus,
    dumps,
    loads,
    utcnow,
)
from app.catalog.schema import SCHEMA

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str, max_len: int = 32) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug[:max_len].strip("-") or "workspace"


def workspace_id_for(seed_url: str) -> str:
    """Stable, collection-name-safe id derived from the URL's host."""
    host = urlparse(seed_url).netloc or seed_url
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return f"{slugify(host, 24)}-{uuid.uuid4().hex[:6]}"


def new_id() -> str:
    return uuid.uuid4().hex


class Catalog:
    """Repository over the workspaces / jobs / queries tables."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        logger.info("Catalog ready at %s", self.db_path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── internals ─────────────────────────────────────────────────────────

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def _all(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ── workspaces ────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_workspace(row: sqlite3.Row) -> Workspace:
        return Workspace(**dict(row))

    def create_workspace(self, ws: Workspace) -> Workspace:
        self._exec(
            """
            INSERT INTO workspaces
                (id, name, seed_url, mode, status, page_count, chunk_count,
                 index_version, max_pages, max_depth, error, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ws.id, ws.name, ws.seed_url, ws.mode, ws.status, ws.page_count,
                ws.chunk_count, ws.index_version, ws.max_pages, ws.max_depth,
                ws.error, ws.created_at, ws.updated_at,
            ),
        )
        return ws

    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        row = self._one("SELECT * FROM workspaces WHERE id = ?", (workspace_id,))
        return self._row_to_workspace(row) if row else None

    def list_workspaces(self) -> List[Workspace]:
        rows = self._all("SELECT * FROM workspaces ORDER BY created_at DESC")
        return [self._row_to_workspace(r) for r in rows]

    def update_workspace(self, workspace_id: str, **fields: Any) -> Optional[Workspace]:
        if not fields:
            return self.get_workspace(workspace_id)
        allowed = {
            "name", "seed_url", "mode", "status", "page_count", "chunk_count",
            "index_version", "max_pages", "max_depth", "error",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Cannot update unknown workspace fields: {sorted(bad)}")
        fields["updated_at"] = utcnow()
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self._exec(
            f"UPDATE workspaces SET {assignments} WHERE id = ?",
            (*fields.values(), workspace_id),
        )
        return self.get_workspace(workspace_id)

    def bump_index_version(self, workspace_id: str) -> int:
        """Invalidates the cached BM25 index for this workspace."""
        self._exec(
            "UPDATE workspaces SET index_version = index_version + 1, updated_at = ? WHERE id = ?",
            (utcnow(), workspace_id),
        )
        ws = self.get_workspace(workspace_id)
        return ws.index_version if ws else 0

    def delete_workspace(self, workspace_id: str) -> bool:
        cur = self._exec("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
        return cur.rowcount > 0

    # ── jobs ──────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        data = dict(row)
        data["result"] = loads(data.get("result"))
        return Job(**data)

    def create_job(self, job: Job) -> Job:
        self._exec(
            """
            INSERT INTO jobs
                (id, workspace_id, kind, status, phase, current, total, message,
                 error, result, created_at, started_at, finished_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job.id, job.workspace_id, job.kind, job.status, job.phase,
                job.current, job.total, job.message, job.error, dumps(job.result),
                job.created_at, job.started_at, job.finished_at,
            ),
        )
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        row = self._one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return self._row_to_job(row) if row else None

    def list_jobs(
        self, workspace_id: Optional[str] = None, limit: int = 50
    ) -> List[Job]:
        if workspace_id:
            rows = self._all(
                "SELECT * FROM jobs WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
                (workspace_id, limit),
            )
        else:
            rows = self._all(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        return [self._row_to_job(r) for r in rows]

    def update_job(self, job_id: str, **fields: Any) -> Optional[Job]:
        if not fields:
            return self.get_job(job_id)
        allowed = {
            "status", "phase", "current", "total", "message", "error",
            "result", "started_at", "finished_at",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Cannot update unknown job fields: {sorted(bad)}")
        if "result" in fields:
            fields["result"] = dumps(fields["result"])
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self._exec(
            f"UPDATE jobs SET {assignments} WHERE id = ?",
            (*fields.values(), job_id),
        )
        return self.get_job(job_id)

    def fail_orphaned_jobs(self) -> int:
        """
        Called on startup: jobs live in-process, so anything still marked
        running belongs to a previous process and can never complete.
        """
        cur = self._exec(
            "UPDATE jobs SET status = ?, error = ?, finished_at = ? "
            "WHERE status IN (?, ?)",
            (
                JobStatus.FAILED,
                "Interrupted by server restart",
                utcnow(),
                JobStatus.RUNNING,
                JobStatus.QUEUED,
            ),
        )
        if cur.rowcount:
            logger.warning("Marked %d orphaned job(s) as failed", cur.rowcount)
            self._exec(
                "UPDATE workspaces SET status = ? WHERE status IN (?, ?)",
                (WorkspaceStatus.FAILED, WorkspaceStatus.CRAWLING, WorkspaceStatus.INDEXING),
            )
        return cur.rowcount

    # ── queries ───────────────────────────────────────────────────────────

    def record_query(self, record: QueryRecord) -> QueryRecord:
        self._exec(
            """
            INSERT INTO queries
                (id, workspace_id, prompt, engine, top_k, answer, citations,
                 elapsed_ms, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                record.id, record.workspace_id, record.prompt, record.engine,
                record.top_k, record.answer, dumps(record.citations),
                record.elapsed_ms, record.created_at,
            ),
        )
        return record

    def list_queries(self, workspace_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self._all(
            "SELECT * FROM queries WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
            (workspace_id, limit),
        )
        out = []
        for r in rows:
            d = dict(r)
            d["citations"] = loads(d.get("citations"))
            out.append(d)
        return out


_catalog: Optional[Catalog] = None
_catalog_lock = threading.Lock()


def get_catalog() -> Catalog:
    """Process-wide catalog singleton."""
    global _catalog
    with _catalog_lock:
        if _catalog is None:
            from app.config import get_settings

            _catalog = Catalog(get_settings().catalog_db)
        return _catalog
