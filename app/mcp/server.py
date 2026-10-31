"""
AskTheSite as an MCP server.

Lets Claude Desktop, Claude Code, Cursor or any MCP client search, read and
question the sites you've indexed. Every tool here delegates to the same
built-in tool the in-app agent uses, so behaviour (and citation numbering
within a call) is identical.

Run over stdio with ``uv run main.py mcp``, or reach it over Streamable HTTP
at ``/mcp`` on the API server.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from mcp.server.mcpserver import MCPServer

from app.agent.citations import CitationLedger
from app.agent.tools import BUILTIN, ToolContext
from app.catalog import get_catalog
from app.config import get_settings

logger = logging.getLogger(__name__)

INSTRUCTIONS = """AskTheSite indexes websites and answers questions about them \
with citations. Start with list_workspaces to see which sites exist, then \
search_site for passages (each carries a [n] citation number), read_page for a \
full page, or ask for a complete cited answer."""


def _context() -> ToolContext:
    workspaces = [w for w in get_catalog().list_workspaces()]
    settings = get_settings()
    return ToolContext(
        session=None, workspaces=workspaces, ledger=CitationLedger(), settings=settings
    )


async def _call(name: str, args: Dict[str, Any]) -> str:
    tool = BUILTIN.get(name)
    result = await tool.run(_context(), args, get_settings().tool_timeout_s)
    if result.is_error:
        # Raising makes the MCP response an error result the client can see.
        raise ValueError(result.content)
    return result.content


def build_server() -> MCPServer:
    server = MCPServer(name="AskTheSite", instructions=INSTRUCTIONS, version="0.3.0")

    @server.tool(description="List the indexed websites with their ids, page and chunk counts.")
    async def list_workspaces() -> str:
        return await _call("list_workspaces", {})

    @server.tool(
        description="Search indexed website content. Returns passages labelled [n] with "
        "their URL. engine: auto (semantic), bm25 (exact keywords) or rerank (most precise)."
    )
    async def search_site(
        query: str,
        workspace: Optional[str] = None,
        engine: str = "auto",
        top_k: int = 5,
    ) -> str:
        return await _call(
            "search_site",
            {"query": query, "workspace": workspace, "engine": engine, "top_k": top_k},
        )

    @server.tool(description="Read the full markdown of one crawled page by its URL.")
    async def read_page(url: str, max_chars: int = 6000) -> str:
        return await _call("read_page", {"url": url, "max_chars": max_chars})

    @server.tool(description="List crawled pages, optionally filtered by text in the title or URL.")
    async def list_pages(
        contains: Optional[str] = None, workspace: Optional[str] = None, limit: int = 40
    ) -> str:
        return await _call("list_pages", {"contains": contains, "workspace": workspace, "limit": limit})

    @server.tool(
        description="Compare semantic, keyword and reranked retrieval for one query and "
        "report how much they agree."
    )
    async def compare_retrieval(query: str, workspace: Optional[str] = None, top_k: int = 5) -> str:
        return await _call("compare_retrieval", {"query": query, "workspace": workspace, "top_k": top_k})

    @server.tool(
        description="Ask a question and get a complete answer with inline [n] citations "
        "and a source list, written by AskTheSite's configured model. mode 'agent' lets it "
        "search several times; 'rag' retrieves once (faster)."
    )
    async def ask(question: str, workspace: Optional[str] = None, mode: str = "rag") -> str:
        from app.agent import TurnOptions, TurnRunner
        from app.services import sessions

        ids = []
        if workspace:
            ctx = _context()
            ws = ctx.workspace(workspace)
            if ws is None:
                raise ValueError(f"No site called {workspace!r}")
            ids = [ws.id]
        session = sessions.create_session(workspace_ids=ids, mode=mode, title=f"MCP · {sessions.title_from(question)}")

        answer, citations, error = "", [], None
        async for event, payload in TurnRunner(session.id, question, TurnOptions(followups=False)).run():
            if event == "answer":
                answer, citations = payload["content"], payload["citations"]
            elif event == "error":
                error = payload["message"]
        if error:
            raise ValueError(error)
        sources = "\n".join(
            f"[{c['marker']}] {c.get('page_title') or c.get('source_url')} — {c.get('source_url')}"
            for c in citations
        )
        return f"{answer}\n\nSources:\n{sources}" if sources else answer

    @server.resource(
        "askthesite://workspaces",
        name="workspaces",
        description="Every indexed site as JSON.",
        mime_type="application/json",
    )
    def workspaces_resource() -> str:
        return json.dumps([w.to_dict() for w in get_catalog().list_workspaces()], indent=2)

    @server.resource(
        "askthesite://workspace/{workspace_id}/pages",
        name="workspace-pages",
        description="The crawl manifest (pages, titles, depths) for one site.",
        mime_type="application/json",
    )
    def pages_resource(workspace_id: str) -> str:
        from app.services import workspaces as ws_service

        return json.dumps(ws_service.list_pages(workspace_id), indent=2)

    return server


_server: Optional[MCPServer] = None


def get_server() -> MCPServer:
    global _server
    if _server is None:
        _server = build_server()
    return _server
