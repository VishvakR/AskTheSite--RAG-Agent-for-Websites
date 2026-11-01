"""Drive the Textual app headlessly with the fake model."""

from textual.widgets import Input, OptionList, Static

from app.services import sessions as svc
from app.tui.app import AskTheSiteApp
from app.tui.widgets import ToolCallBlock, TurnView


async def _ask(app, pilot, text: str) -> None:
    prompt = app.query_one("#prompt", Input)
    prompt.value = text
    await pilot.press("enter")
    await app.workers.wait_for_complete()
    await pilot.pause()


async def test_agent_turn_renders_tools_answer_and_sources(make_workspace):
    ws = make_workspace()
    async with AskTheSiteApp().run_test(size=(160, 50)) as pilot:
        app = pilot.app
        await _ask(app, pilot, "/mode agent")
        await _ask(app, pilot, "How do I install it?")

        [turn] = app.query(TurnView)
        assert [b.tool_name for b in turn.query(ToolCallBlock)] == ["search_site"]
        assert turn.steps[-1]._buffer == "Install it with pip [1]."
        assert turn.steps[0].text.has_class("narration") or not turn.steps[0].text.display
        sources = app.query_one("#sources", OptionList)
        assert sources.option_count >= 1
        # Highlighting a source shows its passage and a link to the page.
        sources.focus()
        await pilot.press("down")
        await pilot.pause()
        detail = str(app.query_one("#source-detail", Static).render())
        assert "https://ex.dev/" in detail

        session = svc.require(app.session.id)
        assert session.mode == "agent" and session.title == "How do I install it?"
        assert ws.id in [o.id for o in app.query_one("#sites", OptionList)._options]


async def test_slash_commands_change_the_session(make_workspace):
    ws = make_workspace()
    async with AskTheSiteApp().run_test(size=(160, 50)) as pilot:
        app = pilot.app
        await _ask(app, pilot, "/engine bm25")
        await _ask(app, pilot, "/topk 3")
        await _ask(app, pilot, "/think off")
        await _ask(app, pilot, f"/site {ws.name}")
        await _ask(app, pilot, "/model fake:fake-2")

        s = svc.require(app.session.id)
        assert (s.engine, s.top_k, s.thinking["enabled"]) == ("bm25", 3, False)
        assert s.workspace_ids == [ws.id]
        assert (s.provider, s.model) == ("fake", "fake-2")
        status = str(app.query_one("#status", Static).render())
        assert "bm25" in status and "fake-2" in status


async def test_reopening_a_chat_restores_history(make_workspace):
    make_workspace()
    async with AskTheSiteApp().run_test(size=(160, 50)) as pilot:
        await _ask(pilot.app, pilot, "How do I install it?")
        session_id = pilot.app.session.id

    # A fresh app opens the most recent chat, loaded from the database.
    async with AskTheSiteApp().run_test(size=(160, 50)) as pilot:
        app = pilot.app
        await pilot.pause()
        assert app.session.id == session_id
        [turn] = app.query(TurnView)
        assert turn.answer["content"] == "Install it with pip [1]."


async def test_model_picker_lists_providers():
    async with AskTheSiteApp().run_test(size=(160, 50)) as pilot:
        await pilot.press("ctrl+o")
        await pilot.pause()
        options = pilot.app.screen.query_one("#models", OptionList)
        assert options.option_count > 3
        await pilot.press("escape")
