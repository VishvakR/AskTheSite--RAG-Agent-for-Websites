"""SQLite schema for the AskTheSite catalog."""

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workspaces (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    seed_url      TEXT NOT NULL,
    mode          TEXT NOT NULL DEFAULT 'page',      -- page | site
    status        TEXT NOT NULL DEFAULT 'empty',     -- empty|crawling|indexing|ready|failed
    page_count    INTEGER NOT NULL DEFAULT 0,
    chunk_count   INTEGER NOT NULL DEFAULT 0,
    index_version INTEGER NOT NULL DEFAULT 0,
    max_pages     INTEGER NOT NULL DEFAULT 100,
    max_depth     INTEGER NOT NULL DEFAULT 3,
    error         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,                      -- crawl | ingest | full
    status       TEXT NOT NULL,                      -- queued|running|succeeded|failed|cancelled
    phase        TEXT NOT NULL DEFAULT '',
    current      INTEGER NOT NULL DEFAULT 0,
    total        INTEGER NOT NULL DEFAULT 0,
    message      TEXT NOT NULL DEFAULT '',
    error        TEXT,
    result       TEXT,                               -- JSON blob
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_workspace ON jobs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status    ON jobs(status);

CREATE TABLE IF NOT EXISTS queries (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    prompt       TEXT NOT NULL,
    engine       TEXT NOT NULL,
    top_k        INTEGER NOT NULL,
    answer       TEXT,
    citations    TEXT,                               -- JSON blob
    elapsed_ms   INTEGER,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_queries_workspace ON queries(workspace_id);
"""
