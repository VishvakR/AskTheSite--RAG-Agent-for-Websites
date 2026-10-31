"""HTTP surface for sessions, models, tools and MCP."""

import json

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    import server

    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _stream(client, path, body):
    events = []
    async with client.stream("POST", path, json=body) as res:
        assert res.status_code == 200, await res.aread()
        name = None
        async for line in res.aiter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                events.append((name, json.loads(line[6:])))
    return events


async def test_session_chat_round_trip(client, make_workspace):
    ws = make_workspace()
    created = await client.post("/sessions", json={"workspace_ids": [ws.id], "mode": "agent"})
    assert created.status_code == 201
    sid = created.json()["session"]["id"]

    events = await _stream(client, f"/sessions/{sid}/chat/stream", {"prompt": "How do I install it?"})
    names = [n for n, _ in events]
    assert names[0] == "turn" and names[-1] == "done"
    assert {"thinking", "tool_call", "tool_result", "sources", "answer", "grounding"} <= set(names)

    detail = (await client.get(f"/sessions/{sid}")).json()
    assert detail["session"]["title"] == "How do I install it?"
    assert detail["session"]["running"] is False
    [turn] = detail["turns"]
    assert turn["steps"][0]["name"] == "search_site"

    listing = (await client.get("/sessions", params={"workspace_id": ws.id})).json()["sessions"]
    assert [s["id"] for s in listing] == [sid]

    hits = (await client.get("/sessions/search", params={"q": "install"})).json()["results"]
    assert any(h["session_id"] == sid for h in hits)


async def test_regenerate_and_edit_replace_the_turn(client, make_workspace):
    ws = make_workspace()
    sid = (await client.post("/sessions", json={"workspace_ids": [ws.id]})).json()["session"]["id"]
    body = {"prompt": "How do I install it?", "followups": False}
    await _stream(client, f"/sessions/{sid}/chat/stream", body)
    turn_id = (await client.get(f"/sessions/{sid}")).json()["turns"][0]["turn_id"]

    await _stream(client, f"/sessions/{sid}/chat/stream", {"replace_turn_id": turn_id, "followups": False})
    turns = (await client.get(f"/sessions/{sid}")).json()["turns"]
    assert len(turns) == 1 and turns[0]["user"]["content"] == "How do I install it?"

    await _stream(
        client, f"/sessions/{sid}/chat/stream",
        {"prompt": "What about proxies?", "replace_turn_id": turns[0]["turn_id"], "followups": False},
    )
    turns = (await client.get(f"/sessions/{sid}")).json()["turns"]
    assert [t["user"]["content"] for t in turns] == ["What about proxies?"]


async def test_session_errors_are_typed(client):
    assert (await client.get("/sessions/nope")).status_code == 404
    assert (await client.post("/sessions", json={"workspace_ids": ["nope"]})).status_code == 422
    assert (await client.post("/sessions", json={"mode": "psychic"})).status_code == 422
    sid = (await client.post("/sessions", json={})).json()["session"]["id"]
    res = await client.post(f"/sessions/{sid}/chat/stream", json={"prompt": "  "})
    assert res.status_code == 422
    res = await client.post(f"/sessions/{sid}/chat/stream", json={"prompt": "x", "replace_turn_id": "zzz"})
    assert res.status_code == 404


async def test_fork_export_feedback_and_delete(client, make_workspace):
    ws = make_workspace()
    sid = (await client.post("/sessions", json={"workspace_ids": [ws.id], "title": "Docs Q&A"})).json()["session"]["id"]
    events = await _stream(client, f"/sessions/{sid}/chat/stream", {"prompt": "How do I install it?"})
    message_id = dict(events)["done"]["message_id"]

    fork = await client.post(f"/sessions/{sid}/fork", json={})
    assert fork.status_code == 201 and fork.json()["session"]["title"] == "Docs Q&A (fork)"

    md = await client.get(f"/sessions/{sid}/export")
    assert md.headers["content-type"].startswith("text/markdown")
    assert 'filename="Docs Q&A.md"'.replace("&", "_") in md.headers["content-disposition"]
    assert "## Answer" in md.text

    fb = await client.post(f"/messages/{message_id}/feedback", json={"value": -1})
    assert fb.json() == {"message_id": message_id, "feedback": -1}

    patched = await client.patch(f"/sessions/{sid}", json={"pinned": True, "title": "Renamed"})
    assert patched.json()["session"]["pinned"] is True

    assert (await client.delete(f"/sessions/{sid}")).json()["deleted"] is True


async def test_models_can_be_hidden_added_and_made_default(client):
    body = (await client.patch("/models/anthropic/claude-haiku-5-5", json={"enabled": False})).json()
    claude = next(p for p in body["providers"] if p["provider"] == "anthropic")
    assert "claude-haiku-5-5" not in claude["models"]
    assert next(s for s in claude["specs"] if s["id"] == "claude-haiku-5-5")["enabled"] is False

    body = (await client.post("/models", json={"provider": "opensource", "model_id": "qwen3:8b", "make_default": True})).json()
    assert body["default"] == "opensource" and body["default_model"] == "qwen3:8b"
    ollama = next(p for p in body["providers"] if p["provider"] == "opensource")
    assert next(s for s in ollama["specs"] if s["id"] == "qwen3:8b")["custom"] is True

    assert (await client.post("/models", json={"provider": "nope", "model_id": "x"})).status_code == 422

    body = (await client.delete("/models/opensource/qwen3:8b")).json()
    assert body["default_model"] != "qwen3:8b"


async def test_tools_can_be_listed_and_toggled(client):
    tools = {t["name"]: t for t in (await client.get("/tools")).json()["tools"]}
    assert tools["search_site"]["enabled"] and not tools["fetch_url"]["enabled"]
    tools = {t["name"]: t for t in (await client.patch("/tools/fetch_url", json={"enabled": True})).json()["tools"]}
    assert tools["fetch_url"]["enabled"]
    assert (await client.patch("/tools/nope", json={"enabled": True})).status_code == 404


async def test_mcp_servers_crud_keeps_secrets_redacted(client):
    res = await client.post("/mcp/servers", json={
        "name": "broken", "transport": "stdio", "command": "/nonexistent/bin", "env": {"TOKEN": "s3cret"},
    })
    assert res.status_code == 201
    [server] = res.json()["servers"]
    assert server["env"] == {"TOKEN": "•••"}
    assert server["status"]["connected"] is False and server["status"]["error"]

    # Sending the redacted value back leaves the secret alone.
    await client.patch(f"/mcp/servers/{server['id']}", json={"env": {"TOKEN": "•••"}, "enabled": False})
    from app.catalog import get_catalog

    assert get_catalog().get_mcp_server(server["id"]).env == {"TOKEN": "s3cret"}

    assert (await client.post(f"/mcp/servers/{server['id']}/test")).status_code == 502
    assert (await client.post("/mcp/servers", json={"name": "x", "transport": "http"})).status_code == 422
    assert (await client.delete(f"/mcp/servers/{server['id']}")).json()["servers"] == []


async def test_api_token_guards_everything_but_health(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "letmein")
    from app.api import create_app
    from app.config import get_settings

    get_settings.cache_clear()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/health")).status_code == 200
        assert (await c.get("/sessions")).status_code == 401
        assert (await c.get("/sessions", headers={"Authorization": "Bearer nope"})).status_code == 401
        assert (await c.get("/sessions", headers={"Authorization": "Bearer letmein"})).status_code == 200


async def test_mcp_is_served_over_http(make_workspace):
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    from app.api import create_app

    ws = make_workspace()
    app = create_app()
    async with app.router.lifespan_context(app):
        http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app))
        async with Client(streamable_http_client("http://localhost:8000/mcp", http_client=http)) as mcp_client:
            result = await mcp_client.call_tool("list_workspaces", {})
            assert ws.id in result.content[0].text
