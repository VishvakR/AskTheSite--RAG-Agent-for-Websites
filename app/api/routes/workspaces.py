"""Workspaces, their crawled data, and single-shot querying."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl

from app.api.deps import resolve_workspace, sse_response
from app.catalog import get_catalog
from app.index.retrieval import compare as compare_retrieval
from app.services import workspaces as ws_service
from app.services.workspaces import WorkspaceBusy

logger = logging.getLogger(__name__)
router = APIRouter()

ENGINES = Literal["auto", "bm25", "rerank"]


class CreateWorkspaceRequest(BaseModel):
    seed_url: HttpUrl = Field(..., description="URL to crawl.")
    name: Optional[str] = Field(None, description="Display name.")
    mode: Literal["page", "site"] = Field("page", description="Single page or whole site.")
    max_pages: Optional[int] = Field(None, ge=1, le=2000)
    max_depth: Optional[int] = Field(None, ge=0, le=10)
    start: bool = Field(True, description="Begin crawling immediately.")


class QueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Question to answer.")
    engine: ENGINES = Field("auto", description="Retrieval strategy.")
    top_k: int = Field(5, ge=1, le=50)
    provider: Optional[str] = Field(None, description="opensource | anthropic | openai | openai_compatible")
    model: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)


class CompareRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    top_k: int = Field(5, ge=1, le=50)


# ── workspaces ────────────────────────────────────────────────────────────


@router.post("/workspaces", status_code=201, tags=["Workspaces"])
async def create_workspace(request: CreateWorkspaceRequest):
    try:
        ws = ws_service.create_workspace(
            seed_url=str(request.seed_url),
            name=request.name,
            mode=request.mode,
            max_pages=request.max_pages,
            max_depth=request.max_depth,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job = ws_service.start_build(ws.id) if request.start else None
    return {"workspace": ws.to_dict(), "job": job.to_dict() if job else None}


@router.get("/workspaces", tags=["Workspaces"])
async def list_workspaces():
    return {"workspaces": [w.to_dict() for w in ws_service.list_workspaces()]}


@router.get("/workspaces/{workspace_id}", tags=["Workspaces"])
async def get_workspace(workspace_id: str):
    return {"workspace": resolve_workspace(workspace_id).to_dict()}


@router.delete("/workspaces/{workspace_id}", tags=["Workspaces"])
async def delete_workspace(workspace_id: str):
    resolve_workspace(workspace_id)
    return {"deleted": ws_service.delete_workspace(workspace_id)}


@router.post("/workspaces/{workspace_id}/reindex", tags=["Workspaces"])
async def reindex_workspace(
    workspace_id: str,
    recrawl: bool = Query(True, description="Re-crawl before indexing."),
):
    resolve_workspace(workspace_id)
    try:
        job = ws_service.start_build(workspace_id, recrawl=recrawl)
    except WorkspaceBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job": job.to_dict()}


# ── workspace data ────────────────────────────────────────────────────────


@router.get("/workspaces/{workspace_id}/documents", tags=["Data"])
async def list_documents(
    workspace_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    q: Optional[str] = None,
):
    resolve_workspace(workspace_id)
    return ws_service.list_documents(workspace_id, page=page, page_size=page_size, q=q)


@router.get("/workspaces/{workspace_id}/pages", tags=["Data"])
async def list_pages(workspace_id: str):
    resolve_workspace(workspace_id)
    return ws_service.list_pages(workspace_id)


@router.get("/workspaces/{workspace_id}/graph", tags=["Data"])
async def workspace_graph(workspace_id: str):
    resolve_workspace(workspace_id)
    return ws_service.graph(workspace_id)


@router.get("/workspaces/{workspace_id}/queries", tags=["Data"])
async def query_history(workspace_id: str, limit: int = Query(25, ge=1, le=200)):
    resolve_workspace(workspace_id)
    return {"queries": get_catalog().list_queries(workspace_id, limit=limit)}


# ── single-shot query (sessionless) ───────────────────────────────────────


def _build_agent(ws, request: QueryRequest):
    try:
        return ws_service.build_agent(
            ws,
            provider=request.provider,
            model=request.model,
            temperature=request.temperature,
            engine=request.engine,
            top_k=request.top_k,
        )
    except ValueError as exc:
        # Missing API key / unknown provider is a configuration problem.
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/workspaces/{workspace_id}/query", tags=["Query"])
async def query_workspace(workspace_id: str, request: QueryRequest):
    ws = resolve_workspace(workspace_id)
    agent = _build_agent(ws, request)
    try:
        answer = await asyncio.to_thread(agent.run, request.prompt)
    except Exception as exc:
        logger.exception("[/query] generation failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    ws_service.record_query(ws, request.prompt, request.engine, request.top_k, answer)
    return answer.to_dict()


@router.post("/workspaces/{workspace_id}/query/stream", tags=["Query"])
async def stream_query(workspace_id: str, request: QueryRequest):
    """
    Server-sent events: ``sources`` first, then ``thinking`` / ``token``
    deltas, then ``done``. For multi-turn chat with memory and tools, use
    ``/sessions/{id}/chat/stream`` instead.
    """
    from app.agent.bridge import iterate_in_thread

    ws = resolve_workspace(workspace_id)
    agent = _build_agent(ws, request)

    async def events():
        chunks: List[str] = []
        citations: List[Dict[str, Any]] = []
        async for event, payload in iterate_in_thread(lambda: agent.stream(request.prompt)):
            if event == "token":
                chunks.append(payload.get("t", ""))
            elif event == "sources":
                citations = payload.get("citations", [])
            yield event, payload
        if chunks:
            class _Rec:
                answer = "".join(chunks)
                elapsed_ms = None
            _Rec.citations = citations
            ws_service.record_query(ws, request.prompt, request.engine, request.top_k, _Rec)

    return sse_response(events())


@router.post("/workspaces/{workspace_id}/retrieval/compare", tags=["Query"])
async def compare_strategies(workspace_id: str, request: CompareRequest):
    """
    The Retrieval Lab: run one question through all three strategies and
    return ranked, comparably-scored chunks plus their overlap.
    """
    ws = resolve_workspace(workspace_id)
    try:
        return await asyncio.to_thread(
            compare_retrieval, ws.collection_name, ws.index_version, request.prompt, request.top_k,
        )
    except Exception as exc:
        logger.exception("[/retrieval/compare] failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
