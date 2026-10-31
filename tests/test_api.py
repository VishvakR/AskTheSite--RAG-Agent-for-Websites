"""HTTP surface, including SSE streaming and typed error codes."""

import json

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    import server

    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health_reports_service_state(client):
    res = await client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "llm_ready" in body and "workspaces" in body


async def test_models_lists_providers_with_reasons(client):
    body = (await client.get("/models")).json()
    providers = {p["provider"]: p for p in body["providers"]}
    assert {"opensource", "anthropic", "openai"} <= set(providers)
    # An unavailable provider must explain itself rather than just being false.
    for p in providers.values():
        assert p["available"] or p["reason"]


async def test_unknown_workspace_is_404_not_500(client):
    """Every failure used to surface as a 500 with a stringified exception."""
    for path in ("", "/documents", "/graph", "/pages"):
        res = await client.get(f"/workspaces/does-not-exist{path}")
        assert res.status_code == 404, path
        assert "does-not-exist" in res.json()["detail"]


async def test_unknown_job_is_404(client):
    assert (await client.get("/jobs/nope")).status_code == 404


async def test_invalid_engine_is_rejected_by_validation(client, make_workspace):
    ws = make_workspace()
    res = await client.post(
        f"/workspaces/{ws.id}/query", json={"prompt": "hi", "engine": "bogus"}
    )
    assert res.status_code == 422


async def test_workspace_lifecycle(client, make_workspace):
    ws = make_workspace()

    listing = (await client.get("/workspaces")).json()["workspaces"]
    assert ws.id in [w["id"] for w in listing]

    detail = (await client.get(f"/workspaces/{ws.id}")).json()["workspace"]
    assert detail["collection_name"] == f"ws_{ws.id}"
    assert detail["chunk_count"] > 0

    docs = (await client.get(f"/workspaces/{ws.id}/documents?page_size=2")).json()
    assert len(docs["documents"]) <= 2
    assert docs["total_chunks"] == detail["chunk_count"]
    assert all(d["source_url"].startswith("https://") for d in docs["documents"])

    graph = (await client.get(f"/workspaces/{ws.id}/graph")).json()
    assert len(graph["nodes"]) == 5

    assert (await client.delete(f"/workspaces/{ws.id}")).json()["deleted"] is True
    assert (await client.get(f"/workspaces/{ws.id}")).status_code == 404


async def test_query_returns_answer_with_citations(client, make_workspace):
    ws = make_workspace()
    res = await client.post(
        f"/workspaces/{ws.id}/query",
        json={"prompt": "how do I install it?", "engine": "auto", "top_k": 3},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["answer"]
    assert body["model"] == "fake-1"
    assert 1 <= len(body["citations"]) <= 3
    # Markers are 1-based and contiguous so inline [n] references resolve.
    assert [c["marker"] for c in body["citations"]] == list(
        range(1, len(body["citations"]) + 1)
    )
    assert all(c["source_url"].startswith("https://") for c in body["citations"])


async def test_stream_sends_sources_before_any_token(client, make_workspace):
    """The UI renders the citation panel while the answer is still generating."""
    ws = make_workspace()
    events = []
    async with client.stream(
        "POST",
        f"/workspaces/{ws.id}/query/stream",
        json={"prompt": "how do I install it?", "engine": "auto", "top_k": 3},
    ) as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        async for line in res.aiter_lines():
            if line.startswith("event: "):
                events.append(line[7:])
            elif line.startswith("data: ") and events and events[-1] == "sources":
                payload = json.loads(line[6:])
                assert payload["citations"]

    assert events[0] == "sources"
    assert "token" in events
    assert events[-1] == "done"
    assert events.index("sources") < events.index("token")


async def test_compare_endpoint_returns_all_three_strategies(client, make_workspace):
    ws = make_workspace()
    res = await client.post(
        f"/workspaces/{ws.id}/retrieval/compare",
        json={"prompt": "install the library", "top_k": 3},
    )
    assert res.status_code == 200
    body = res.json()
    assert set(body["strategies"]) == {"auto", "bm25", "rerank"}
    assert set(body["overlap"]["pairwise"]) == {
        "auto|bm25",
        "auto|rerank",
        "bm25|rerank",
    }


async def test_query_history_is_recorded(client, make_workspace):
    ws = make_workspace()
    await client.post(
        f"/workspaces/{ws.id}/query", json={"prompt": "first question", "engine": "auto"}
    )
    history = (await client.get(f"/workspaces/{ws.id}/queries")).json()["queries"]
    assert history and history[0]["prompt"] == "first question"
