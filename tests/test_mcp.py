"""MCP in both directions."""

import os
import sys
from pathlib import Path

from mcp import Client

from app.catalog import MCPServerConfig, get_catalog, new_id
from app.mcp.client import Connection, MCPClientManager, tool_name
from app.mcp.server import build_server

ROOT = Path(__file__).resolve().parents[1]


def _text(result) -> str:
    return "\n".join(getattr(b, "text", "") for b in result.content)


async def test_server_exposes_site_tools_and_answers(make_workspace):
    ws = make_workspace()
    async with Client(build_server()) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert {"list_workspaces", "search_site", "read_page", "list_pages", "ask", "compare_retrieval"} <= names

        listing = await client.call_tool("list_workspaces", {})
        assert ws.id in _text(listing)

        hits = await client.call_tool("search_site", {"query": "install crawl4ai", "top_k": 2})
        assert not hits.is_error and "[1]" in _text(hits)

        page = await client.call_tool("read_page", {"url": "https://ex.dev/install"})
        assert "pip install crawl4ai" in _text(page)

        answer = await client.call_tool("ask", {"question": "How do I install it?"})
        assert "Install it with pip [1]." in _text(answer) and "Sources:" in _text(answer)


async def test_server_reports_tool_errors_as_error_results():
    async with Client(build_server()) as client:
        result = await client.call_tool("read_page", {"url": "https://nowhere.dev"})
        assert result.is_error


def test_tool_names_are_provider_safe():
    assert tool_name("My Server!", "do.thing") == "mcp__My_Server___do_thing"
    assert len(tool_name("s" * 80, "t" * 80)) == 64


async def test_client_adapts_remote_tools_for_the_agent(make_workspace, monkeypatch):
    ws = make_workspace()
    cfg = MCPServerConfig(id=new_id(), name="self", transport="stdio", command="unused")
    monkeypatch.setattr(Connection, "_target", lambda self: build_server())

    conn = Connection(cfg)
    await conn.start()
    try:
        tools = {t.name: t for t in conn.as_tools()}
        search = tools["mcp__self__search_site"]
        assert search.source == "mcp:self" and search.schema()["required"] == ["query"]

        from app.agent.citations import CitationLedger
        from app.agent.tools import ToolContext

        ctx = ToolContext(session=None, workspaces=[ws], ledger=CitationLedger())
        result = await search.run(ctx, {"query": "install"}, timeout=30)
        assert not result.is_error and "ex.dev" in result.content
    finally:
        await conn.stop()


async def test_manager_reports_unreachable_servers_without_raising():
    get_catalog().create_mcp_server(
        MCPServerConfig(id=new_id(), name="broken", transport="stdio", command="/nonexistent/binary")
    )
    manager = MCPClientManager()
    await manager.sync()
    [status] = manager.status().values()
    assert status["connected"] is False and status["error"]
    assert manager.tools() == []
    await manager.shutdown()


async def test_stdio_round_trip_against_our_own_server(tmp_path):
    """Launch `main.py mcp` as a real subprocess and talk to it over stdio."""
    env = {
        "PYTHONPATH": str(ROOT),
        "CATALOG_DB": os.environ["CATALOG_DB"],
        "PERSISTENT_STORAGE": os.environ["PERSISTENT_STORAGE"],
        "WORKSPACE_ROOT": os.environ["WORKSPACE_ROOT"],
        "LOG_LEVEL": "WARNING",
    }
    cfg = MCPServerConfig(
        id=new_id(), name="askthesite", transport="stdio",
        command=sys.executable, args=[str(ROOT / "main.py"), "mcp"], env=env,
    )
    tools = await MCPClientManager().test(cfg)
    assert "search_site" in {t["name"] for t in tools}
