"""
The HTTP API, assembled from one router per area.

``server.py`` just calls :func:`create_app`; keeping the routes here means
each area (workspaces, sessions, models, MCP, jobs) can grow without turning
one module into a thousand lines.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import TokenGuard
from app.api.routes import ROUTERS
from app.api.routes.utility import VERSION
from app.catalog import get_catalog
from app.config import get_settings
from app.jobs import get_runner

logger = logging.getLogger(__name__)

DESCRIPTION = (
    "Crawl a website, index it, and ask it questions. Answers carry inline "
    "citations, retrieval strategies can be compared side by side, chats keep "
    "their memory in sessions, and an agent mode lets the model search and "
    "read pages itself. The same tools are served over MCP at /mcp."
)


def create_app() -> FastAPI:
    from app.mcp.client import get_mcp_manager
    from app.mcp.server import get_server

    settings = get_settings()
    mcp_server = get_server()
    # Builds the Streamable HTTP session manager; its routes are lifted into
    # this app below so the endpoint lives at exactly /mcp.
    security = None
    if settings.mcp_allowed_hosts:
        from mcp.server.transport_security import TransportSecuritySettings

        security = TransportSecuritySettings(
            allowed_hosts=settings.mcp_allowed_hosts,
            allowed_origins=[f"{scheme}://{h}" for h in settings.mcp_allowed_hosts for scheme in ("http", "https")],
        )
    mcp_http = mcp_server.streamable_http_app(streamable_http_path="/mcp", transport_security=security)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("AskTheSite API starting up …")
        get_runner().bind_loop(asyncio.get_running_loop())
        # Jobs live in-process, so anything still marked running belongs to a
        # previous process and can never finish.
        get_catalog().fail_orphaned_jobs()
        manager = get_mcp_manager()
        # Connecting to external MCP servers can be slow; don't block startup.
        connect = asyncio.create_task(manager.sync())
        async with mcp_server.session_manager.run():
            yield
        connect.cancel()
        await manager.shutdown()
        await get_runner().shutdown()
        logger.info("AskTheSite API shut down.")

    app = FastAPI(title="AskTheSite API", description=DESCRIPTION, version=VERSION, lifespan=lifespan)

    for router in ROUTERS:
        app.include_router(router)
    app.router.routes.extend(mcp_http.routes)

    if settings.api_token:
        app.add_middleware(TokenGuard, token=settings.api_token)
    # Added last so it wraps everything, including 401s from the guard.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    return app
