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

from app.catalog.migrations import migrate
from app.catalog.models import (
    Job,
    JobStatus,
    MCPServerConfig,
    MessageRecord,
    ModelSetting,
    QueryRecord,
    Session,
    Workspace,
    WorkspaceStatus,
    dumps,
    loads,
    utcnow,
)

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
    """
    Repository over the catalog tables: workspaces, jobs, queries, sessions,
    messages, model settings and MCP servers.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            version = migrate(self._conn)
        logger.info("Catalog ready at %s (schema v%d)", self.db_path, version)

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


    # ── json row helpers ──────────────────────────────────────────────────

    @staticmethod
    def _decode(row: sqlite3.Row, json_fields, bool_fields=()) -> Dict[str, Any]:
        data = dict(row)
        for key in json_fields:
            if key in data:
                data[key] = loads(data[key])
        for key in bool_fields:
            if key in data:
                data[key] = bool(data[key])
        return data

    def _update(
        self, table: str, key_sql: str, key: tuple, allowed: set, json_fields, fields: Dict[str, Any]
    ) -> None:
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Cannot update unknown {table} fields: {sorted(bad)}")
        values = []
        for name, value in fields.items():
            if name in json_fields:
                value = dumps(value)
            elif isinstance(value, bool):
                value = int(value)
            values.append(value)
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE {table} SET {assignments} WHERE {key_sql}", (*values, *key))

    # ── sessions ──────────────────────────────────────────────────────────

    def _row_to_session(self, row: sqlite3.Row) -> Session:
        data = self._decode(row, Session.JSON_FIELDS, ("pinned",))
        data["workspace_ids"] = data.get("workspace_ids") or []
        return Session(**data)

    def create_session(self, session: Session) -> Session:
        self._exec(
            """
            INSERT INTO sessions
                (id, title, workspace_ids, provider, model, mode, engine, top_k,
                 thinking, system_prompt, pinned, summary, summary_upto, usage,
                 created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                session.id, session.title, dumps(session.workspace_ids),
                session.provider, session.model, session.mode, session.engine,
                session.top_k, dumps(session.thinking), session.system_prompt,
                int(session.pinned), session.summary, session.summary_upto,
                dumps(session.usage), session.created_at, session.updated_at,
            ),
        )
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        row = self._one("SELECT * FROM sessions WHERE id = ?", (session_id,))
        return self._row_to_session(row) if row else None

    def list_sessions(
        self, workspace_id: Optional[str] = None, limit: int = 100
    ) -> List[Session]:
        if workspace_id:
            # workspace_ids is a JSON array; json_each keeps the match exact.
            rows = self._all(
                """
                SELECT s.* FROM sessions s
                WHERE EXISTS (SELECT 1 FROM json_each(s.workspace_ids) WHERE value = ?)
                ORDER BY s.pinned DESC, s.updated_at DESC LIMIT ?
                """,
                (workspace_id, limit),
            )
        else:
            rows = self._all(
                "SELECT * FROM sessions ORDER BY pinned DESC, updated_at DESC LIMIT ?",
                (limit,),
            )
        return [self._row_to_session(r) for r in rows]

    def update_session(self, session_id: str, **fields: Any) -> Optional[Session]:
        if fields:
            allowed = {
                "title", "workspace_ids", "provider", "model", "mode", "engine",
                "top_k", "thinking", "system_prompt", "pinned", "summary",
                "summary_upto", "usage",
            }
            fields["updated_at"] = utcnow()
            self._update(
                "sessions", "id = ?", (session_id,), allowed | {"updated_at"},
                Session.JSON_FIELDS, fields,
            )
        return self.get_session(session_id)

    def touch_session(self, session_id: str) -> None:
        self._exec("UPDATE sessions SET updated_at = ? WHERE id = ?", (utcnow(), session_id))

    def delete_session(self, session_id: str) -> bool:
        cur = self._exec("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cur.rowcount > 0

    def detach_workspace(self, workspace_id: str) -> int:
        """Drop a deleted workspace from every session that referenced it."""
        cur = self._exec(
            """
            UPDATE sessions SET workspace_ids = (
                SELECT COALESCE(json_group_array(value), '[]')
                FROM json_each(sessions.workspace_ids) WHERE value != ?
            )
            WHERE EXISTS (SELECT 1 FROM json_each(sessions.workspace_ids) WHERE value = ?)
            """,
            (workspace_id, workspace_id),
        )
        return cur.rowcount

    # ── messages ──────────────────────────────────────────────────────────

    def _row_to_message(self, row: sqlite3.Row) -> MessageRecord:
        return MessageRecord(**self._decode(row, MessageRecord.JSON_FIELDS, ("is_error",)))

    def next_seq(self, session_id: str) -> int:
        row = self._one(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM messages WHERE session_id = ?",
            (session_id,),
        )
        return row["n"]

    def add_message(self, msg: MessageRecord) -> MessageRecord:
        with self._lock:
            if not msg.seq:
                msg.seq = self.next_seq(msg.session_id)
            self._exec(
                """
                INSERT INTO messages
                    (id, session_id, turn_id, seq, role, content, thinking,
                     tool_calls, tool_call_id, name, is_error, raw, raw_provider,
                     citations, trace, grounding, followups, usage, provider,
                     model, elapsed_ms, feedback, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    msg.id, msg.session_id, msg.turn_id, msg.seq, msg.role,
                    msg.content, msg.thinking, dumps(msg.tool_calls),
                    msg.tool_call_id, msg.name, int(msg.is_error), dumps(msg.raw),
                    msg.raw_provider, dumps(msg.citations), dumps(msg.trace),
                    dumps(msg.grounding), dumps(msg.followups), dumps(msg.usage),
                    msg.provider, msg.model, msg.elapsed_ms, msg.feedback,
                    msg.created_at,
                ),
            )
        return msg

    def get_message(self, message_id: str) -> Optional[MessageRecord]:
        row = self._one("SELECT * FROM messages WHERE id = ?", (message_id,))
        return self._row_to_message(row) if row else None

    def list_messages(
        self, session_id: str, after_seq: int = 0, before_seq: Optional[int] = None
    ) -> List[MessageRecord]:
        sql = "SELECT * FROM messages WHERE session_id = ? AND seq > ?"
        params: tuple = (session_id, after_seq)
        if before_seq is not None:
            sql += " AND seq < ?"
            params += (before_seq,)
        rows = self._all(sql + " ORDER BY seq", params)
        return [self._row_to_message(r) for r in rows]

    def update_message(self, message_id: str, **fields: Any) -> Optional[MessageRecord]:
        if fields:
            allowed = {"grounding", "followups", "feedback", "trace", "citations"}
            self._update(
                "messages", "id = ?", (message_id,), allowed, MessageRecord.JSON_FIELDS, fields
            )
        return self.get_message(message_id)

    def delete_messages_from(self, session_id: str, seq: int) -> int:
        """Truncate a session at *seq* (inclusive) -- used by edit & regenerate."""
        cur = self._exec(
            "DELETE FROM messages WHERE session_id = ? AND seq >= ?", (session_id, seq)
        )
        return cur.rowcount

    def search_messages(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Full-text search across every session, best matches first."""
        terms = [t for t in re.findall(r"[\w-]+", query) if t]
        if not terms:
            return []
        match = " ".join(f'"{t}"*' for t in terms)
        rows = self._all(
            """
            SELECT f.message_id, f.session_id, s.title, m.role, m.created_at,
                   snippet(messages_fts, 0, '[', ']', '…', 12) AS snippet
            FROM messages_fts f
            JOIN messages m ON m.id = f.message_id
            JOIN sessions s ON s.id = f.session_id
            WHERE messages_fts MATCH ?
            ORDER BY rank LIMIT ?
            """,
            (match, limit),
        )
        return [dict(r) for r in rows]

    # ── model settings ────────────────────────────────────────────────────

    def list_model_settings(self) -> List[ModelSetting]:
        rows = self._all("SELECT * FROM model_settings")
        return [
            ModelSetting(**self._decode(r, ("params",), ("enabled", "is_default")))
            for r in rows
        ]

    def upsert_model_setting(
        self,
        provider: str,
        model_id: str,
        enabled: Optional[bool] = None,
        is_default: Optional[bool] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> ModelSetting:
        with self._lock:
            row = self._one(
                "SELECT * FROM model_settings WHERE provider = ? AND model_id = ?",
                (provider, model_id),
            )
            current = (
                ModelSetting(**self._decode(row, ("params",), ("enabled", "is_default")))
                if row
                else ModelSetting(provider=provider, model_id=model_id)
            )
            if enabled is not None:
                current.enabled = enabled
            if is_default is not None:
                current.is_default = is_default
            if params is not None:
                current.params = params
            current.updated_at = utcnow()
            if current.is_default:
                # Exactly one default model across all providers.
                self._exec("UPDATE model_settings SET is_default = 0")
            self._exec(
                """
                INSERT INTO model_settings (provider, model_id, enabled, is_default, params, updated_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT (provider, model_id) DO UPDATE SET
                    enabled = excluded.enabled, is_default = excluded.is_default,
                    params = excluded.params, updated_at = excluded.updated_at
                """,
                (
                    provider, model_id, int(current.enabled), int(current.is_default),
                    dumps(current.params), current.updated_at,
                ),
            )
        return current

    # ── MCP servers ───────────────────────────────────────────────────────

    def _row_to_mcp(self, row: sqlite3.Row) -> MCPServerConfig:
        return MCPServerConfig(**self._decode(row, MCPServerConfig.JSON_FIELDS, ("enabled",)))

    def create_mcp_server(self, cfg: MCPServerConfig) -> MCPServerConfig:
        self._exec(
            """
            INSERT INTO mcp_servers
                (id, name, transport, command, args, env, url, headers, enabled,
                 created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cfg.id, cfg.name, cfg.transport, cfg.command, dumps(cfg.args),
                dumps(cfg.env), cfg.url, dumps(cfg.headers), int(cfg.enabled),
                cfg.created_at, cfg.updated_at,
            ),
        )
        return cfg

    def get_mcp_server(self, server_id: str) -> Optional[MCPServerConfig]:
        row = self._one("SELECT * FROM mcp_servers WHERE id = ?", (server_id,))
        return self._row_to_mcp(row) if row else None

    def list_mcp_servers(self, enabled_only: bool = False) -> List[MCPServerConfig]:
        sql = "SELECT * FROM mcp_servers"
        if enabled_only:
            sql += " WHERE enabled = 1"
        return [self._row_to_mcp(r) for r in self._all(sql + " ORDER BY name")]

    def update_mcp_server(self, server_id: str, **fields: Any) -> Optional[MCPServerConfig]:
        if fields:
            allowed = {"name", "transport", "command", "args", "env", "url", "headers", "enabled"}
            fields["updated_at"] = utcnow()
            self._update(
                "mcp_servers", "id = ?", (server_id,), allowed | {"updated_at"},
                MCPServerConfig.JSON_FIELDS, fields,
            )
        return self.get_mcp_server(server_id)

    def delete_mcp_server(self, server_id: str) -> bool:
        return self._exec("DELETE FROM mcp_servers WHERE id = ?", (server_id,)).rowcount > 0

    # ── app settings ──────────────────────────────────────────────────────

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self._one("SELECT value FROM app_settings WHERE key = ?", (key,))
        return loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self._exec(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, dumps(value)),
        )


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
