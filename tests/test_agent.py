"""The agent harness: both modes, tools, citations, grounding, limits."""

import threading

import pytest

from app.agent import TurnOptions, TurnRunner
from app.agent.bridge import iterate_in_thread
from app.agent.citations import CitationLedger
from app.agent.grounding import assess
from app.agent.tools import describe_all, enabled_tools, set_enabled
from app.llm.types import ChatMessage, Stop, TextDelta, ToolCall, ToolCallEvent, Usage
from app.services import sessions as svc


async def _collect(runner):
    return [event async for event in runner.run()]


def _names(events):
    return [name for name, _ in events]


async def test_rag_turn_streams_sources_first_and_persists(make_workspace):
    ws = make_workspace()
    s = svc.create_session(workspace_ids=[ws.id], mode="rag")

    events = await _collect(TurnRunner(s.id, "How do I install it?"))
    names = _names(events)

    assert names[0] == "turn"
    assert names.index("sources") < names.index("token") < names.index("answer")
    assert names[-1] == "done"
    assert "title" in names and svc.require(s.id).title == "How do I install it?"

    [turn] = svc.turns(s.id)
    assert turn["user"]["content"] == "How do I install it?"
    assert turn["answer"]["content"] == "Install it with pip [1]."
    assert turn["answer"]["citations"][0]["marker"] == 1
    assert turn["answer"]["grounding"]["label"] == "grounded"
    assert svc.require(s.id).usage["input_tokens"] > 0


async def test_rag_history_replays_the_prompt_the_model_saw(make_workspace):
    ws = make_workspace()
    s = svc.create_session(workspace_ids=[ws.id])
    await _collect(TurnRunner(s.id, "How do I install it?", TurnOptions(followups=False)))

    first = svc.history(svc.require(s.id))[0]
    assert first.role == "user" and "=== SOURCES ===" in first.content


async def test_markers_continue_across_turns(make_workspace):
    ws = make_workspace()
    s = svc.create_session(workspace_ids=[ws.id], top_k=2)
    opts = TurnOptions(followups=False)
    await _collect(TurnRunner(s.id, "install with pip", opts))
    events = await _collect(TurnRunner(s.id, "rate limits and proxies", opts))

    first, second = (t["answer"]["citations"] for t in svc.turns(s.id))
    by_key = {(c["source_url"], c["chunk_index"]): c["marker"] for c in first}
    for c in second:
        key = (c["source_url"], c["chunk_index"])
        if key in by_key:
            assert c["marker"] == by_key[key]  # same chunk, same number
        else:
            assert c["marker"] > max(by_key.values())  # new chunk, new number
    assert events[-1][0] == "done"


async def test_agent_turn_calls_tools_then_answers(make_workspace):
    ws = make_workspace()
    s = svc.create_session(workspace_ids=[ws.id], mode="agent")

    events = await _collect(TurnRunner(s.id, "How do I install it?"))
    names = _names(events)

    assert names.count("step") == 2
    assert names.index("thinking") < names.index("tool_call") < names.index("tool_result")
    assert names.index("tool_result") < names.index("sources") < names.index("answer")
    result = dict(events)["tool_result"]
    assert result["name"] == "search_site" and not result["is_error"]
    assert "followups" in names

    [turn] = svc.turns(s.id)
    assert [step["name"] for step in turn["steps"]] == ["search_site"]
    assert turn["answer"]["thinking"] == "I should search the site first."
    assert turn["answer"]["citations"]
    kinds = [t["kind"] for t in turn["answer"]["trace"]]
    assert kinds == ["model", "tool", "model"]


async def test_agent_falls_back_to_rag_without_tool_support(make_workspace, monkeypatch):
    from app.llm.manager import LanguageModelFactory
    from app.llm.registry import ModelSpec

    fake = LanguageModelFactory._registry["fake"]
    monkeypatch.setattr(fake, "spec_for", classmethod(lambda cls, m, s=None: ModelSpec("fake", m)))
    ws = make_workspace()
    s = svc.create_session(workspace_ids=[ws.id], mode="agent")

    events = await _collect(TurnRunner(s.id, "How do I install it?", TurnOptions(followups=False)))
    assert dict(events)["turn"]["mode"] == "rag"
    assert "notice" in _names(events) and "tool_call" not in _names(events)


class _Looper:
    """Calls a tool forever -- the harness must cut it off."""

    model_name = "looper"

    def chat(self, messages, tools=None, thinking=None):
        n = sum(1 for m in messages if m.role == "tool")
        call = ToolCall(f"c{n}", "no_such_tool", {})
        yield ToolCallEvent(call)
        yield Usage(1, 1)
        yield Stop("tool_use", ChatMessage(role="assistant", content="still looking", tool_calls=[call]))


async def test_step_limit_forces_a_final_answer(make_workspace, monkeypatch):
    monkeypatch.setenv("AGENT_MAX_STEPS", "2")
    from app.config import get_settings

    get_settings.cache_clear()
    s = svc.create_session(mode="agent")
    events = await _collect(
        TurnRunner(s.id, "loop please", TurnOptions(followups=False), llm=_Looper())
    )
    names = _names(events)
    assert names.count("step") == 3  # two research steps + the forced final one
    results = [p for n, p in events if n == "tool_result"]
    assert all(r["is_error"] for r in results)
    assert "Step limit" in [p for n, p in events if n == "notice"][-1]["message"]
    assert names[-1] == "done"

    [turn] = svc.turns(s.id)
    assert turn["user"]["content"] == "loop please"  # the harness note is hidden


async def test_cancel_stops_the_turn(make_workspace):
    ws = make_workspace()
    s = svc.create_session(workspace_ids=[ws.id])
    cancel = threading.Event()
    cancel.set()
    events = await _collect(TurnRunner(s.id, "How?", TurnOptions(followups=False), cancel=cancel))
    assert dict(events)["done"]["cancelled"] is True


async def test_empty_prompt_is_an_error():
    s = svc.create_session()
    assert _names(await _collect(TurnRunner(s.id, "   "))) == ["error"]


def test_invalid_tool_arguments_become_a_readable_error():
    import asyncio

    from app.agent.tools import BUILTIN, ToolContext

    tool = BUILTIN.get("search_site")
    ctx = ToolContext(session=None, workspaces=[], ledger=CitationLedger())
    result = asyncio.run(tool.run(ctx, {"top_k": 999}, timeout=5))
    assert result.is_error and "query" in result.content and "top_k" in result.content


def test_fetch_is_opt_in_and_tools_can_be_toggled():
    names = {t.name for t in enabled_tools()}
    assert "search_site" in names and "fetch_url" not in names
    set_enabled("search_site", False)
    assert "search_site" not in {t.name for t in enabled_tools()}
    row = next(t for t in describe_all() if t["name"] == "search_site")
    assert row["enabled"] is False and row["input_schema"]["required"] == ["query"]
    with pytest.raises(ValueError):
        set_enabled("nope", True)


def test_ledger_reuses_markers_for_the_same_chunk():
    ledger = CitationLedger(prior=[{"marker": 4, "chunk_id": "a"}])
    assert ledger.add({"chunk_id": "a", "score": 0.9})["marker"] == 4
    assert ledger.add({"chunk_id": "b"})["marker"] == 5
    assert [c["marker"] for c in ledger.turn_citations()] == [4, 5]


def test_grounding_flags_uncited_claims_and_bad_markers():
    cites = [{"marker": 1}, {"marker": 2}]
    report = assess(
        "Install it with pip install crawl4ai [1]. Then run the setup command once. "
        "It writes a config file into your home folder [1].\n\n"
        "It needs Python three point nine [7].\n\n- Headless mode is on by default [2]",
        cites,
    )
    assert report["sentences"] == 5
    # "Then run the setup…" is covered by the citation on the sentence after it;
    # the [7] sentence is not, because [7] points at no source.
    assert report["supported"] == 4
    assert report["invalid_markers"] == [7]
    assert report["uncited"] == ["It needs Python three point nine ."]
    assert report["unused_sources"] == []


def test_grounding_ignores_disclaimers_headings_and_lead_ins():
    report = assess(
        "# Answer\n\nThe sources do not mention pricing at all.\n\n"
        "A minimal crawl looks like this:\n\n```py\nx = 1\n```",
        [{"marker": 1}],
    )
    assert report["score"] is None and report["label"] == "n/a"


async def test_bridge_propagates_errors():
    def boom():
        yield TextDelta("a")
        raise RuntimeError("provider exploded")

    seen = []
    with pytest.raises(RuntimeError, match="exploded"):
        async for item in iterate_in_thread(boom):
            seen.append(item)
    assert seen == [TextDelta("a")]
