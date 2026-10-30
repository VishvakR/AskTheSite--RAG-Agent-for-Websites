"""Catalog migrations and the session service."""

import sqlite3

import pytest

from app.catalog.migrations import LATEST, current_version
from app.catalog.schema import SCHEMA
from app.catalog.store import Catalog
from app.llm import ChatMessage, ToolCall
from app.services import sessions as svc


def test_pre_migration_database_upgrades_in_place(tmp_path):
    """A catalog created before migrations existed has user_version 0."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO workspaces (id, name, seed_url, created_at, updated_at) "
        "VALUES ('w1', 'Old', 'https://old.dev', 'x', 'x')"
    )
    conn.commit()
    conn.close()

    catalog = Catalog(path)
    assert current_version(catalog._conn) == LATEST
    assert catalog.get_workspace("w1").name == "Old"
    assert catalog.list_sessions() == []


def _turn(session_id, turn_id, question, answer, calls=()):
    svc.append(session_id, turn_id, ChatMessage.user(question))
    if calls:
        svc.append(session_id, turn_id, ChatMessage(role="assistant", thinking="plan", tool_calls=list(calls)))
        for call in calls:
            svc.append(session_id, turn_id, ChatMessage.tool_result(call, f"result of {call.name}"))
    svc.append(
        session_id, turn_id, ChatMessage(role="assistant", content=answer),
        citations=[{"marker": 1, "page_title": "Install", "source_url": "https://ex.dev/install"}],
    )


def test_session_defaults_come_from_settings():
    session = svc.create_session()
    assert session.provider == "fake"
    assert session.mode == "rag" and session.title == "New chat"


def test_unknown_workspace_or_mode_is_rejected():
    with pytest.raises(ValueError):
        svc.create_session(workspace_ids=["nope"])
    with pytest.raises(ValueError):
        svc.create_session(mode="telepathy")


def test_turns_fold_tool_steps_under_their_answer():
    s = svc.create_session()
    call = ToolCall("c1", "search_site", {"query": "install"})
    _turn(s.id, "t1", "How do I install it?", "Use pip [1].", calls=[call])

    [turn] = svc.turns(s.id)
    assert turn["user"]["content"] == "How do I install it?"
    assert turn["steps"] == [{
        "id": "c1", "name": "search_site", "arguments": {"query": "install"},
        "result": "result of search_site", "is_error": False, "elapsed_ms": None,
    }]
    assert turn["answer"]["content"] == "Use pip [1]."
    assert turn["answer"]["thinking"] == "plan"
    assert "raw" not in turn["answer"]


def test_history_replays_every_message_in_order():
    s = svc.create_session()
    _turn(s.id, "t1", "q1", "a1", calls=[ToolCall("c1", "list_pages", {})])
    roles = [m.role for m in svc.history(svc.require(s.id))]
    assert roles == ["user", "assistant", "tool", "assistant"]


def test_truncate_returns_question_and_drops_the_suffix():
    s = svc.create_session()
    _turn(s.id, "t1", "first", "a1")
    _turn(s.id, "t2", "second", "a2")
    assert svc.truncate_at_turn(s.id, "t2") == "second"
    assert [t["turn_id"] for t in svc.turns(s.id)] == ["t1"]


def test_fork_copies_up_to_a_turn():
    s = svc.create_session(title="Original")
    _turn(s.id, "t1", "first", "a1")
    _turn(s.id, "t2", "second", "a2")
    copy = svc.fork(s.id, upto_turn_id="t1")
    assert copy.id != s.id and copy.title == "Original (fork)"
    assert [t["user"]["content"] for t in svc.turns(copy.id)] == ["first"]
    # The original is untouched.
    assert len(svc.turns(s.id)) == 2


def test_search_finds_messages_across_sessions():
    a, b = svc.create_session(), svc.create_session()
    _turn(a.id, "t1", "How do proxies work?", "Configure them in browser options [1].")
    _turn(b.id, "t1", "Unrelated", "Nothing here.")
    hits = svc.search("proxies")
    assert hits and {h["session_id"] for h in hits} == {a.id}


def test_export_markdown_lists_sources():
    s = svc.create_session(title="Install help")
    _turn(s.id, "t1", "How?", "Use pip [1].")
    md = svc.export(s.id)
    assert md.startswith("# Install help")
    assert "1. [Install](https://ex.dev/install)" in md


def test_compaction_folds_old_turns_into_a_summary():
    s = svc.create_session()
    for i in range(4):
        _turn(s.id, f"t{i}", f"question {i}", f"answer {i}")

    class Summariser:
        model_name = "s"

        def stream_response(self, prompt):
            yield "They asked four questions."

    updated = svc.compact(svc.require(s.id), Summariser(), keep_turns=2)
    assert updated.summary == "They asked four questions."
    replay = svc.history(updated)
    assert replay[0].role == "system" and "four questions" in replay[0].content
    assert [m.content for m in replay if m.role == "user"] == ["question 2", "question 3"]


def test_feedback_validates_value():
    s = svc.create_session()
    record = svc.append(s.id, "t1", ChatMessage(role="assistant", content="x"))
    assert svc.set_feedback(record.id, 1).feedback == 1
    with pytest.raises(ValueError):
        svc.set_feedback(record.id, 5)


def test_deleting_a_workspace_detaches_it_from_sessions(make_workspace):
    from app.services import workspaces

    ws = make_workspace()
    s = svc.create_session(workspace_ids=[ws.id])
    workspaces.delete_workspace(ws.id)
    assert svc.require(s.id).workspace_ids == []
