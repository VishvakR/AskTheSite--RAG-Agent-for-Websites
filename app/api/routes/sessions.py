"""Chat sessions: memory, the agent harness, and everything around a turn."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.agent import SessionBusy, TurnOptions, TurnRunner, runs
from app.api.deps import sse_response
from app.services import sessions as svc

router = APIRouter(tags=["Sessions"])

Mode = Literal["rag", "agent"]
Engine = Literal["auto", "bm25", "rerank"]


class Thinking(BaseModel):
    enabled: bool = True
    effort: Optional[Literal["low", "medium", "high"]] = None


class SessionFields(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    workspace_ids: Optional[List[str]] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    mode: Optional[Mode] = None
    engine: Optional[Engine] = None
    top_k: Optional[int] = Field(None, ge=1, le=20)
    thinking: Optional[Thinking] = None
    system_prompt: Optional[str] = Field(None, max_length=4000)
    pinned: Optional[bool] = None


class ChatRequest(BaseModel):
    prompt: str = Field("", description="The question. May be empty when regenerating.")
    replace_turn_id: Optional[str] = Field(
        None, description="Drop this turn and everything after it first (regenerate / edit)."
    )
    provider: Optional[str] = None
    model: Optional[str] = None
    mode: Optional[Mode] = None
    engine: Optional[Engine] = None
    top_k: Optional[int] = Field(None, ge=1, le=20)
    thinking: Optional[Thinking] = None
    followups: Optional[bool] = None


class ForkRequest(BaseModel):
    turn_id: Optional[str] = None


class FeedbackRequest(BaseModel):
    value: Literal[-1, 0, 1]


def _require(session_id: str):
    try:
        return svc.require(session_id)
    except svc.SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _fields(body: SessionFields) -> Dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    if "thinking" in data and data["thinking"] is not None:
        data["thinking"] = body.thinking.model_dump()
    return data


@router.post("/sessions", status_code=201)
async def create_session(body: SessionFields):
    data = _fields(body)
    data.pop("pinned", None)
    try:
        session = svc.create_session(**data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"session": session.to_dict()}


@router.get("/sessions")
async def list_sessions(workspace_id: Optional[str] = None, limit: int = Query(100, ge=1, le=500)):
    active = set(runs.active())
    return {
        "sessions": [
            s.to_dict() | {"running": s.id in active}
            for s in svc.list_sessions(workspace_id, limit)
        ]
    }


@router.get("/sessions/search")
async def search_sessions(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=100)):
    return {"results": svc.search(q, limit)}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    _require(session_id)
    detail = svc.detail(session_id)
    detail["session"]["running"] = session_id in runs.active()
    return detail


@router.patch("/sessions/{session_id}")
async def update_session(session_id: str, body: SessionFields):
    _require(session_id)
    try:
        session = svc.update_session(session_id, **_fields(body))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"session": session.to_dict()}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    _require(session_id)
    runs.cancel(session_id)
    return {"deleted": svc.delete_session(session_id)}


@router.post("/sessions/{session_id}/chat/stream")
async def chat_stream(session_id: str, body: ChatRequest):
    """
    Answer one question in the session as server-sent events. See
    ``app.agent.loop`` for the event vocabulary; ``turn`` always comes first
    and ``done`` (or ``error``) last.
    """
    _require(session_id)

    stack = ExitStack()
    try:
        cancel = stack.enter_context(runs.claim(session_id))
    except SessionBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        prompt = body.prompt.strip()
        if body.replace_turn_id:
            original = svc.truncate_at_turn(session_id, body.replace_turn_id)
            prompt = prompt or original
        if not prompt:
            raise HTTPException(status_code=422, detail="prompt is required")
    except ValueError as exc:
        stack.close()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        stack.close()
        raise

    options = TurnOptions(
        provider=body.provider,
        model=body.model,
        mode=body.mode,
        engine=body.engine,
        top_k=body.top_k,
        thinking=body.thinking.model_dump() if body.thinking else None,
        followups=body.followups,
    )
    runner = TurnRunner(session_id, prompt, options, cancel=cancel)

    async def events():
        try:
            async for event in runner.run():
                yield event
        finally:
            # Client gone or turn over: stop any in-flight model stream.
            cancel.set()
            stack.close()

    return sse_response(events())


@router.post("/sessions/{session_id}/cancel")
async def cancel_session(session_id: str):
    _require(session_id)
    return {"cancelled": runs.cancel(session_id)}


@router.post("/sessions/{session_id}/fork", status_code=201)
async def fork_session(session_id: str, body: ForkRequest):
    _require(session_id)
    try:
        session = svc.fork(session_id, body.turn_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"session": session.to_dict()}


@router.get("/sessions/{session_id}/export")
async def export_session(session_id: str, format: Literal["markdown", "json"] = "markdown"):
    session = _require(session_id)
    text = svc.export(session_id, format)
    ext, media = ("md", "text/markdown") if format == "markdown" else ("json", "application/json")
    safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in session.title).strip() or "session"
    return PlainTextResponse(
        text,
        media_type=f"{media}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}.{ext}"'},
    )


@router.post("/messages/{message_id}/feedback")
async def message_feedback(message_id: str, body: FeedbackRequest):
    try:
        record = svc.set_feedback(message_id, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"message_id": record.id, "feedback": record.feedback}
