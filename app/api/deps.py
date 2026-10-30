"""Helpers shared by the route modules."""

from __future__ import annotations

import hmac
import json
from typing import Any, AsyncIterator, Tuple

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.services import workspaces as ws_service
from app.services.workspaces import WorkspaceNotFound

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def resolve_workspace(workspace_id: str):
    try:
        return ws_service.require(workspace_id)
    except WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def sse_response(events: AsyncIterator[Tuple[str, Any]]) -> StreamingResponse:
    async def body():
        async for event, data in events:
            yield sse(event, data)

    return StreamingResponse(body(), media_type="text/event-stream", headers=SSE_HEADERS)


class TokenGuard:
    """
    Optional bearer-token auth for the whole API, including SSE and ``/mcp``.

    Pure ASGI rather than ``BaseHTTPMiddleware`` so streamed responses pass
    through untouched. Off unless ``API_TOKEN`` is set.
    """

    OPEN = ("/health", "/docs", "/redoc", "/openapi.json")

    def __init__(self, app, token: str):
        self.app = app
        self.token = token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] == "OPTIONS" or scope["path"].startswith(self.OPEN):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"")
        supplied = auth[7:] if auth.lower().startswith(b"bearer ") else b""
        if supplied and hmac.compare_digest(supplied, self.token):
            return await self.app(scope, receive, send)
        body = json.dumps({"detail": "Missing or invalid API token"}).encode()
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")],
        })
        await send({"type": "http.response.body", "body": body})
