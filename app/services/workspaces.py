"""
Workspace orchestration: create, build (crawl + ingest), inspect, delete.

This is the layer the HTTP routes sit on. Keeping it out of ``server.py`` means
the same operations are callable from the CLI and from tests without a client.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any, Dict, List, Optional

from app.catalog import (
    Job,
    JobKind,
    QueryRecord,
    Workspace,
    WorkspaceStatus,
    get_catalog,
    new_id,
    workspace_id_for,
)
from app.config import get_settings
from app.crawler.main import WebCrawler
from app.crawler.pages import WorkspaceStore
from app.index.providers.chroma import ChromaIndex
from app.index.providers.type import QueryEngineType
from app.ingestion import Documents
from app.jobs import get_runner
from app.llm import LLMManager
from app.main import RAGAgent
from app.runtime.resources import get_store, invalidate_workspace

logger = logging.getLogger(__name__)


class WorkspaceNotFound(Exception):
    pass


class WorkspaceBusy(Exception):
    pass


# ── helpers ───────────────────────────────────────────────────────────────


def require(workspace_id: str) -> Workspace:
    ws = get_catalog().get_workspace(workspace_id)
    if ws is None:
        raise WorkspaceNotFound(f"No workspace with id {workspace_id!r}")
    return ws


def workspace_dir(ws: Workspace):
    return get_settings().workspace_dir(ws.id)


def build_agent(
    ws: Workspace,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    engine: str = QueryEngineType.AUTO.value,
    top_k: int = 5,
) -> RAGAgent:
    """
    Construct an agent for one request.

    Cheap, because the expensive pieces (embedding model, Chroma handle,
    cross-encoder, BM25 index) live in ``app.runtime.resources``.
    """
    settings = get_settings()
    provider = provider or settings.llm_provider

    kwargs: Dict[str, Any] = {}
    if model:
        kwargs["model_name"] = model
    if temperature is not None:
        kwargs["temperature"] = temperature

    llm = LLMManager.create(provider, **kwargs)
    return RAGAgent(
        llm=llm,
        collection_name=ws.collection_name,
        index_version=ws.index_version,
        engine=engine,
        top_k=top_k,
        phoenix_api_key=settings.phoenix_api_key,
    )


# ── CRUD ──────────────────────────────────────────────────────────────────


def create_workspace(
    seed_url: str,
    name: Optional[str] = None,
    mode: str = "page",
    max_pages: Optional[int] = None,
    max_depth: Optional[int] = None,
) -> Workspace:
    settings = get_settings()
    if mode not in ("page", "site"):
        raise ValueError("mode must be 'page' or 'site'")

    ws = Workspace(
        id=workspace_id_for(seed_url),
        name=(name or seed_url).strip(),
        seed_url=seed_url,
        mode=mode,
        max_pages=max_pages or settings.crawl_max_pages,
        max_depth=max_depth if max_depth is not None else settings.crawl_max_depth,
    )
    get_catalog().create_workspace(ws)
    workspace_dir(ws).mkdir(parents=True, exist_ok=True)
    logger.info("Created workspace %s (%s)", ws.id, ws.seed_url)
    return ws


def delete_workspace(workspace_id: str) -> bool:
    ws = require(workspace_id)
    try:
        get_store(ws.collection_name).drop()
    except Exception:
        logger.exception("Failed dropping collection for %s", ws.id)
    invalidate_workspace(ws.collection_name)
    shutil.rmtree(workspace_dir(ws), ignore_errors=True)
    # Sessions outlive the sites they searched; they just stop searching this one.
    get_catalog().detach_workspace(ws.id)
    return get_catalog().delete_workspace(ws.id)


def list_workspaces() -> List[Workspace]:
    return get_catalog().list_workspaces()


# ── build (crawl + ingest) ────────────────────────────────────────────────


def _index_sync(ws: Workspace, on_progress) -> int:
    """Blocking chunk-and-embed pass; always called via ``asyncio.to_thread``."""
    catalog = get_catalog()
    fresh = catalog.get_workspace(ws.id) or ws
    documents = Documents(workspace_dir(fresh), workspace_id=fresh.id)
    index = ChromaIndex(
        collection_name=fresh.collection_name,
        document=documents,
        index_version=fresh.index_version,
    )
    return index.create_index(reset=True, on_progress=on_progress)


def start_build(workspace_id: str, recrawl: bool = True) -> Job:
    """
    Kick off crawl (optional) then ingest, as one background job.

    Returns immediately with the job record; progress streams over
    ``GET /jobs/{id}/events``.
    """
    ws = require(workspace_id)
    catalog = get_catalog()
    runner = get_runner()

    if ws.status in (WorkspaceStatus.CRAWLING, WorkspaceStatus.INDEXING):
        raise WorkspaceBusy(f"Workspace {ws.id} is already {ws.status}")

    async def work(job_id: str) -> Dict[str, Any]:
        pages = 0
        try:
            if recrawl:
                catalog.update_workspace(ws.id, status=WorkspaceStatus.CRAWLING, error=None)
                crawler = WebCrawler()
                cb = runner.progress_callback(job_id, "crawl")
                target = workspace_dir(ws)

                if ws.mode == "site":
                    records = await crawler.crawl_site(
                        ws.seed_url,
                        target,
                        max_pages=ws.max_pages,
                        max_depth=ws.max_depth,
                        on_progress=cb,
                    )
                else:
                    records = await crawler.crawl_page(ws.seed_url, target, on_progress=cb)

                pages = sum(1 for r in records if r.ok)
                failed = [r for r in records if not r.ok]
                if pages == 0:
                    detail = failed[0].error if failed else "no pages returned content"
                    raise RuntimeError(f"Crawl produced no usable pages: {detail}")
                catalog.update_workspace(ws.id, page_count=pages)
            else:
                manifest = WorkspaceStore(workspace_dir(ws)).read_manifest() or {}
                pages = int(manifest.get("page_count", 0))

            catalog.update_workspace(ws.id, status=WorkspaceStatus.INDEXING)
            version = catalog.bump_index_version(ws.id)
            refreshed = catalog.get_workspace(ws.id)

            chunks = await asyncio.to_thread(
                _index_sync, refreshed, runner.progress_callback(job_id, "ingest")
            )

            catalog.update_workspace(
                ws.id,
                status=WorkspaceStatus.READY,
                chunk_count=chunks,
                page_count=pages,
                error=None,
            )
            return {"pages": pages, "chunks": chunks, "index_version": version}

        except Exception as exc:
            catalog.update_workspace(
                ws.id, status=WorkspaceStatus.FAILED, error=str(exc)
            )
            raise

    kind = JobKind.FULL if recrawl else JobKind.INGEST
    return runner.submit(ws.id, kind, work)


# ── inspection ────────────────────────────────────────────────────────────


def list_documents(
    workspace_id: str, page: int = 1, page_size: int = 25, q: Optional[str] = None
) -> Dict[str, Any]:
    """Paginated view of the indexed chunks."""
    ws = require(workspace_id)
    store = get_store(ws.collection_name)
    raw = store.get_vector_store().get()

    ids = raw.get("ids") or []
    texts = raw.get("documents") or []
    metas = raw.get("metadatas") or []

    rows = []
    for i, text in enumerate(texts):
        meta = metas[i] if i < len(metas) else {}
        if q and q.lower() not in (text or "").lower():
            continue
        flat = " ".join((text or "").split())
        rows.append(
            {
                "id": ids[i] if i < len(ids) else None,
                "summary": flat[:200] + ("…" if len(flat) > 200 else ""),
                "length": len(text or ""),
                "source_url": (meta or {}).get("source_url", ""),
                "page_title": (meta or {}).get("page_title", ""),
                "heading": (meta or {}).get("heading", ""),
                "chunk_index": (meta or {}).get("chunk_index", 0),
                "metadata": meta or {},
            }
        )

    rows.sort(key=lambda r: (r["source_url"], r["chunk_index"]))
    total = len(rows)
    page = max(1, page)
    start = (page - 1) * page_size
    return {
        "documents": rows[start : start + page_size],
        "total_chunks": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


def list_pages(workspace_id: str) -> Dict[str, Any]:
    ws = require(workspace_id)
    manifest = WorkspaceStore(workspace_dir(ws)).read_manifest()
    return manifest or {"seed_url": ws.seed_url, "pages": [], "page_count": 0}


def graph(workspace_id: str) -> Dict[str, Any]:
    ws = require(workspace_id)
    data = WorkspaceStore(workspace_dir(ws)).graph()

    # Annotate nodes with how many chunks each page contributed.
    try:
        raw = get_store(ws.collection_name).get_vector_store().get()
        counts: Dict[str, int] = {}
        for meta in raw.get("metadatas") or []:
            pid = (meta or {}).get("page_id")
            if pid:
                counts[pid] = counts.get(pid, 0) + 1
        for node in data["nodes"]:
            node["chunk_count"] = counts.get(node["id"], 0)
    except Exception:
        logger.exception("Could not annotate graph with chunk counts")

    return data


def record_query(ws: Workspace, prompt: str, engine: str, top_k: int, answer) -> None:
    try:
        get_catalog().record_query(
            QueryRecord(
                id=new_id(),
                workspace_id=ws.id,
                prompt=prompt,
                engine=engine,
                top_k=top_k,
                answer=getattr(answer, "answer", None),
                citations=getattr(answer, "citations", None),
                elapsed_ms=getattr(answer, "elapsed_ms", None),
            )
        )
    except Exception:
        logger.exception("Failed to record query history")
