"""
Test fixtures.

Every test runs against a throwaway storage root so the suite never touches
the developer's real ``./storage`` or ``./workspaces`` directories, and uses a
deterministic fake LLM so no network or Ollama daemon is required.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, List

import pytest


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point every path-based setting at a temp dir and reset the singletons."""
    monkeypatch.setenv("PERSISTENT_STORAGE", str(tmp_path / "chroma"))
    monkeypatch.setenv("CATALOG_DB", str(tmp_path / "catalog.db"))
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("CRAWL_HEADLESS", "true")

    from app.config import get_settings

    get_settings.cache_clear()

    import app.catalog.store as store_module
    import app.runtime.resources as resources

    store_module._catalog = None
    resources.reset_all()

    yield tmp_path

    store_module._catalog = None
    resources.reset_all()
    get_settings.cache_clear()


class FakeLLM:
    """Deterministic stand-in for a real provider."""

    provider = "fake"
    model_name = "fake-1"

    def __init__(self, model_name: str = "fake-1", temperature: float = 0.0, **_: object):
        self.model_name = model_name
        self.temperature = temperature

    def generate_response(self, prompt: str) -> str:
        return "Install it with pip [1]."

    def stream_response(self, prompt: str) -> Iterator[str]:
        for piece in ["Install ", "it ", "with ", "pip ", "[1]."]:
            yield piece

    @classmethod
    def spec_for(cls, model_id: str, settings=None):
        from app.llm.registry import ModelSpec

        return ModelSpec(
            "fake", model_id, context_window=100_000,
            supports_tools=True, supports_thinking=True,
        )

    def chat(self, messages, tools=None, thinking=None):
        """
        Agent-style when tools are offered: think, call ``search_site`` with
        the question, then answer citing [1] once the result is back.
        """
        from app.llm.main import chat_via_prompt
        from app.llm.types import ChatMessage, Stop, ThinkingDelta, ToolCall, ToolCallEvent, Usage

        last_user = max(i for i, m in enumerate(messages) if m.role == "user")
        searched = any(m.role == "tool" for m in messages[last_user:])
        if tools and not searched:
            call = ToolCall("call_1", "search_site", {"query": messages[last_user].content})
            yield ThinkingDelta("I should search the site first.")
            yield ToolCallEvent(call)
            yield Usage(12, 4)
            yield Stop("tool_use", ChatMessage(
                role="assistant", thinking="I should search the site first.", tool_calls=[call],
            ))
            return
        yield Usage(20, 6)
        yield from chat_via_prompt(self, messages)

    def describe(self) -> dict:
        return {"provider": self.provider, "model": self.model_name}


@pytest.fixture(autouse=True)
def register_fake_llm() -> Iterator[None]:
    from app.llm.manager import LanguageModelFactory

    LanguageModelFactory._registry["fake"] = FakeLLM  # type: ignore[assignment]
    yield


@pytest.fixture
def make_workspace(tmp_path: Path):
    """Create a workspace with pages already on disk, then index it."""

    def _make(
        pages: List[tuple[str, str, str]] | None = None,
        seed: str = "https://ex.dev",
        outlinks: dict[str, list[str]] | None = None,
    ):
        from app.crawler.pages import PageRecord, WorkspaceStore
        from app.index.providers.chroma import ChromaIndex
        from app.ingestion import Documents
        from app.services import workspaces as svc
        from app.catalog import get_catalog

        # Deliberately more than a couple of pages: BM25's IDF term is
        # degenerate on a tiny corpus (a word in 1 of 2 documents scores
        # exactly 0), so a 2-page fixture cannot exercise keyword retrieval.
        pages = pages or [
            ("https://ex.dev/install", "Install",
             "# Install\n\nRun pip install crawl4ai to get started with the library."),
            ("https://ex.dev/usage", "Usage",
             "# Usage\n\nCall the crawler with an async context manager and await the result."),
            ("https://ex.dev/config", "Config",
             "# Config\n\nBrowser options control headless mode, viewport size and timeouts."),
            ("https://ex.dev/faq", "FAQ",
             "# FAQ\n\nCommon questions about rate limits, robots handling and proxies."),
            ("https://ex.dev/changelog", "Changelog",
             "# Changelog\n\nRelease notes describing fixes, features and breaking changes."),
        ]
        ws = svc.create_workspace(seed_url=seed, name="Test", mode="site")

        store = WorkspaceStore(svc.workspace_dir(ws))
        records = []
        for url, title, body in pages:
            rec = PageRecord(url=url, title=title, outlinks=(outlinks or {}).get(url, []))
            store.write_page(rec, body)
            records.append(rec)
        store.write_manifest(seed, records, mode="site")

        version = get_catalog().bump_index_version(ws.id)
        fresh = get_catalog().get_workspace(ws.id)
        index = ChromaIndex(
            collection_name=fresh.collection_name,
            document=Documents(svc.workspace_dir(ws), workspace_id=ws.id),
            index_version=version,
        )
        chunks = index.create_index(reset=True)
        get_catalog().update_workspace(
            ws.id, status="ready", page_count=len(pages), chunk_count=chunks
        )
        return get_catalog().get_workspace(ws.id)

    return _make
