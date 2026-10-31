"""
Ordered, versioned schema migrations.

The applied version lives in SQLite's own ``PRAGMA user_version``, so there is
no bookkeeping table to get out of sync. Migration 1 is the original schema;
it is written with ``IF NOT EXISTS`` throughout, so databases created before
migrations existed (user_version 0) upgrade cleanly instead of erroring.

To change the schema, append a new ``(version, name, sql)`` entry -- never edit
one that has shipped.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import List, Tuple

from app.catalog.schema import SCHEMA

logger = logging.getLogger(__name__)

SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL DEFAULT 'New chat',
    workspace_ids TEXT NOT NULL DEFAULT '[]',        -- JSON list
    provider      TEXT,
    model         TEXT,
    mode          TEXT NOT NULL DEFAULT 'rag',       -- rag | agent
    engine        TEXT NOT NULL DEFAULT 'auto',
    top_k         INTEGER NOT NULL DEFAULT 5,
    thinking      TEXT,                              -- JSON ThinkingConfig
    system_prompt TEXT,
    pinned        INTEGER NOT NULL DEFAULT 0,
    summary       TEXT,
    summary_upto  INTEGER NOT NULL DEFAULT 0,        -- last seq folded into summary
    usage         TEXT,                              -- JSON running token totals
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_id      TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    role         TEXT NOT NULL,                      -- user|assistant|tool|system
    content      TEXT NOT NULL DEFAULT '',
    thinking     TEXT,
    tool_calls   TEXT,                               -- JSON
    tool_call_id TEXT,
    name         TEXT,
    is_error     INTEGER NOT NULL DEFAULT 0,
    raw          TEXT,                               -- JSON, provider-native blocks
    raw_provider TEXT,
    citations    TEXT,                               -- JSON
    trace        TEXT,                               -- JSON agent timeline
    grounding    TEXT,                               -- JSON
    followups    TEXT,                               -- JSON
    usage        TEXT,                               -- JSON
    provider     TEXT,
    model        TEXT,
    elapsed_ms   INTEGER,
    feedback     INTEGER NOT NULL DEFAULT 0,         -- -1 | 0 | 1
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, seq);

-- Full-text search over what people asked and what they were told.
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    message_id UNINDEXED,
    session_id UNINDEXED,
    tokenize = 'porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages
WHEN new.role IN ('user', 'assistant') AND new.content != ''
BEGIN
    INSERT INTO messages_fts (content, message_id, session_id)
    VALUES (new.content, new.id, new.session_id);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages
BEGIN
    DELETE FROM messages_fts WHERE message_id = old.id;
END;
"""

SETTINGS = """
CREATE TABLE IF NOT EXISTS model_settings (
    provider   TEXT NOT NULL,
    model_id   TEXT NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    is_default INTEGER NOT NULL DEFAULT 0,
    params     TEXT,                                 -- JSON
    updated_at TEXT NOT NULL,
    PRIMARY KEY (provider, model_id)
);

CREATE TABLE IF NOT EXISTS mcp_servers (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    transport  TEXT NOT NULL DEFAULT 'stdio',        -- stdio | http
    command    TEXT,
    args       TEXT NOT NULL DEFAULT '[]',
    env        TEXT NOT NULL DEFAULT '{}',
    url        TEXT,
    headers    TEXT NOT NULL DEFAULT '{}',
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL                              -- JSON
);
"""

MIGRATIONS: List[Tuple[int, str, str]] = [
    (1, "initial schema", SCHEMA),
    (2, "sessions and messages", SESSIONS),
    (3, "model settings, MCP servers, app settings", SETTINGS),
]

LATEST = MIGRATIONS[-1][0]


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> int:
    """Apply every pending migration in order; return the resulting version."""
    version = current_version(conn)
    for number, name, sql in MIGRATIONS:
        if number <= version:
            continue
        logger.info("Applying catalog migration %d: %s", number, name)
        try:
            conn.executescript(sql)
            conn.execute(f"PRAGMA user_version = {int(number)}")
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Catalog migration %d failed", number)
            raise
        version = number
    return version
