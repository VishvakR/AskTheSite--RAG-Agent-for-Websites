"""AskTheSite HTTP API."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, HttpUrl

from app.catalog import get_catalog
from app.config import get_settings
from app.index.retrieval import compare as compare_retrieval
from app.index.providers.type import QueryEngineType
from app.jobs import get_runner
from app.llm import LLMManager
from app.logger import Logger
from app.services import workspaces as ws_service
from app.services.workspaces import WorkspaceBusy, WorkspaceNotFound

load_dotenv()
settings = get_settings()
Logger.setup(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AskTheSite API starting up …")
    get_runner().bind_loop(asyncio.get_running_loop())
    # Jobs live in-process, so anything still marked running belongs to a
    # previous process and can never finish.
    get_catalog().fail_orphaned_jobs()
    yield
    await get_runner().shutdown()
    logger.info("AskTheSite API shut down.")


app = FastAPI(
    title="AskTheSite API",
    description=(
        "Crawl a website, index it, and query it with natural language. "
        "Retrieval is inspectable: every answer carries citations, and the "
        "three retrieval strategies can be compared side by side."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ENGINES = Literal["auto", "bm25", "rerank"]


# ── schemas ───────────────────────────────────────────────────────────────


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
    provider: Optional[str] = Field(None, description="opensource | anthropic | openai")
    model: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)


class CompareRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    top_k: int = Field(5, ge=1, le=50)


# ── error mapping ─────────────────────────────────────────────────────────


def _resolve(workspace_id: str):
    try:
        return ws_service.require(workspace_id)
    except WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ── utility ───────────────────────────────────────────────────────────────


@app.get("/health", tags=["Utility"])
async def health_check():
    providers = LLMManager.availability()
    return {
        "status": "ok",
        "service": "AskTheSite API",
        "version": app.version,
        "workspaces": len(ws_service.list_workspaces()),
        "llm_ready": any(p["available"] for p in providers),
    }


@app.get("/models", tags=["Utility"])
async def list_models():
    """Which LLM providers are usable right now, and why not if they aren't."""
    return {"providers": LLMManager.availability(), "default": settings.llm_provider}


# ── workspaces ────────────────────────────────────────────────────────────


@app.post("/workspaces", status_code=201, tags=["Workspaces"])
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


@app.get("/workspaces", tags=["Workspaces"])
async def list_workspaces():
    return {"workspaces": [w.to_dict() for w in ws_service.list_workspaces()]}


@app.get("/workspaces/{workspace_id}", tags=["Workspaces"])
async def get_workspace(workspace_id: str):
    return {"workspace": _resolve(workspace_id).to_dict()}


@app.delete("/workspaces/{workspace_id}", tags=["Workspaces"])
async def delete_workspace(workspace_id: str):
    _resolve(workspace_id)
    return {"deleted": ws_service.delete_workspace(workspace_id)}


@app.post("/workspaces/{workspace_id}/reindex", tags=["Workspaces"])
async def reindex_workspace(
    workspace_id: str,
    recrawl: bool = Query(True, description="Re-crawl before indexing."),
):
    _resolve(workspace_id)
    try:
        job = ws_service.start_build(workspace_id, recrawl=recrawl)
    except WorkspaceBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job": job.to_dict()}


# ── workspace data ────────────────────────────────────────────────────────


@app.get("/workspaces/{workspace_id}/documents", tags=["Data"])
async def list_documents(
    workspace_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    q: Optional[str] = None,
):
    _resolve(workspace_id)
    return ws_service.list_documents(workspace_id, page=page, page_size=page_size, q=q)


@app.get("/workspaces/{workspace_id}/pages", tags=["Data"])
async def list_pages(workspace_id: str):
    _resolve(workspace_id)
    return ws_service.list_pages(workspace_id)


@app.get("/workspaces/{workspace_id}/graph", tags=["Data"])
async def workspace_graph(workspace_id: str):
    _resolve(workspace_id)
    return ws_service.graph(workspace_id)


@app.get("/workspaces/{workspace_id}/queries", tags=["Data"])
async def query_history(workspace_id: str, limit: int = Query(25, ge=1, le=200)):
    _resolve(workspace_id)
    return {"queries": get_catalog().list_queries(workspace_id, limit=limit)}


# ── query ─────────────────────────────────────────────────────────────────


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


@app.post("/workspaces/{workspace_id}/query", tags=["Query"])
async def query_workspace(workspace_id: str, request: QueryRequest):
    ws = _resolve(workspace_id)
    agent = _build_agent(ws, request)
    try:
        answer = await asyncio.to_thread(agent.run, request.prompt)
    except Exception as exc:
        logger.exception("[/query] generation failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    ws_service.record_query(ws, request.prompt, request.engine, request.top_k, answer)
    return answer.to_dict()


@app.post("/workspaces/{workspace_id}/query/stream", tags=["Query"])
async def stream_query(workspace_id: str, request: QueryRequest):
    """
    Server-sent events: ``sources`` first, then ``token``s, then ``done``.

    Sources lead so the UI can render the citation panel while the answer is
    still being generated.
    """
    ws = _resolve(workspace_id)
    agent = _build_agent(ws, request)

    async def generate():
        queue: asyncio.Queue = asyncio.Queue(maxsize=512)
        sentinel = object()

        def produce():
            try:
                for event, payload in agent.stream(request.prompt):
                    queue.put_nowait((event, payload))
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("[/query/stream] failed")
                queue.put_nowait(("error", {"message": str(exc)}))
            finally:
                queue.put_nowait(sentinel)

        task = asyncio.create_task(asyncio.to_thread(produce))
        chunks: List[str] = []
        citations: List[Dict[str, Any]] = []
        try:
            while True:
                item = await queue.get()
                if item is sentinel:
                    break
                event, payload = item
                if event == "token":
                    chunks.append(payload.get("t", ""))
                elif event == "sources":
                    citations = payload.get("citations", [])
                yield _sse(event, payload)
        finally:
            await task
            if chunks:
                class _Rec:
                    answer = "".join(chunks)
                    elapsed_ms = None
                _Rec.citations = citations
                ws_service.record_query(
                    ws, request.prompt, request.engine, request.top_k, _Rec
                )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/workspaces/{workspace_id}/retrieval/compare", tags=["Query"])
async def compare_strategies(workspace_id: str, request: CompareRequest):
    """
    The Retrieval Lab: run one question through all three strategies and
    return ranked, comparably-scored chunks plus their overlap.
    """
    ws = _resolve(workspace_id)
    try:
        return await asyncio.to_thread(
            compare_retrieval,
            ws.collection_name,
            ws.index_version,
            request.prompt,
            request.top_k,
        )
    except Exception as exc:
        logger.exception("[/retrieval/compare] failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ── jobs ──────────────────────────────────────────────────────────────────


@app.get("/jobs", tags=["Jobs"])
async def list_jobs(
    workspace_id: Optional[str] = None, limit: int = Query(50, ge=1, le=200)
):
    return {"jobs": [j.to_dict() for j in get_catalog().list_jobs(workspace_id, limit)]}


@app.get("/jobs/{job_id}", tags=["Jobs"])
async def get_job(job_id: str):
    job = get_catalog().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id!r}")
    return job.to_dict()


@app.get("/jobs/{job_id}/events", tags=["Jobs"])
async def job_events(job_id: str):
    """Live progress for a job as server-sent events."""
    if get_catalog().get_job(job_id) is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id!r}")

    async def generate():
        async for message in get_runner().subscribe(job_id):
            yield _sse(message["event"], message["data"])

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/jobs/{job_id}/cancel", tags=["Jobs"])
async def cancel_job(job_id: str):
    if get_catalog().get_job(job_id) is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id!r}")
    return {"cancelled": get_runner().cancel(job_id)}
