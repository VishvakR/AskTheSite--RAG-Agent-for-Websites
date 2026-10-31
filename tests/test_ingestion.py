"""Chunk metadata and header-aware splitting."""

from pathlib import Path

from app.crawler.pages import PageRecord, WorkspaceStore
from app.ingestion import Documents

MARKDOWN = """# Guide

Intro paragraph.

## Installation

Run pip install.

## Usage

Call the crawler.
"""


def _workspace(tmp_path: Path) -> Path:
    store = WorkspaceStore(tmp_path)
    rec = PageRecord(url="https://a.dev/guide", title="Guide", depth=1)
    store.write_page(rec, MARKDOWN)
    store.write_manifest("https://a.dev", [rec])
    return tmp_path


def test_every_chunk_carries_its_source(tmp_path: Path):
    chunks = Documents(_workspace(tmp_path), workspace_id="ws1").create_nodes()
    assert chunks
    for c in chunks:
        assert c.metadata["source_url"] == "https://a.dev/guide"
        assert c.metadata["page_title"] == "Guide"
        assert c.metadata["workspace_id"] == "ws1"
        assert c.metadata["page_id"]


def test_chunks_keep_their_heading_breadcrumb(tmp_path: Path):
    chunks = Documents(_workspace(tmp_path)).create_nodes()
    headings = {c.metadata["heading"] for c in chunks}
    assert "Guide > Installation" in headings
    assert "Guide > Usage" in headings


def test_chunk_index_is_sequential_per_page(tmp_path: Path):
    chunks = Documents(_workspace(tmp_path)).create_nodes()
    indexes = [c.metadata["chunk_index"] for c in chunks]
    assert indexes == list(range(len(chunks)))


def test_empty_directory_yields_no_chunks(tmp_path: Path):
    assert Documents(tmp_path).create_nodes() == []
