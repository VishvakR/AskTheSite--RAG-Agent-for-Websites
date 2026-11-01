"""
AskTheSite in the terminal.

    uv run main.py tui

Runs the same sessions, agent harness and MCP tools as the web app, in
process -- no API server needed. Left: sites and chats. Middle: the
conversation, with thinking and tool calls folded inline. Right: the sources
behind the latest answer.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from app.agent import TurnRunner, runs
from app.catalog import Session, get_catalog
from app.llm import LLMManager
from app.services import sessions
from app.tui.screens import CrawlScreen, HelpScreen, ModelPicker, SearchScreen
from app.tui.widgets import FollowUp, TurnView, format_tokens, grounding_label

logger = logging.getLogger(__name__)

ALL_SITES = "__all__"
ENGINES = ("auto", "bm25", "rerank")


class AskTheSiteApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "AskTheSite"

    BINDINGS = [
        Binding("ctrl+n", "new_chat", "New chat"),
        Binding("ctrl+o", "pick_model", "Model"),
        Binding("ctrl+t", "toggle_mode", "rag/agent"),
        Binding("ctrl+r", "retry", "Retry"),
        Binding("ctrl+s", "export", "Export"),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", show=False),
        Binding("escape", "stop", "Stop", show=False),
        Binding("f1", "help", "Help"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.session: Optional[Session] = None
        self.site_filter: Optional[str] = None
        self.cancel = None
        self._last_usage: Optional[Dict[str, int]] = None
        self._sources: List[Dict[str, Any]] = []

    # ── layout ────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label("◆ AskTheSite", id="brand")
                yield Label("SITES", classes="section")
                yield OptionList(id="sites")
                yield Label("CHATS", classes="section")
                yield OptionList(id="chats")
            with Vertical(id="main"):
                yield Label("New chat", id="title")
                yield VerticalScroll(id="chat")
                yield Input(placeholder="Ask about your sites…  (/help for commands)", id="prompt")
                yield Static("", id="status")
            with Vertical(id="inspector"):
                yield Label("SOURCES", classes="section")
                yield OptionList(id="sources")
                yield Static("[dim]Sources for the latest answer appear here.[/]", id="source-detail")
        yield Footer()

    async def on_mount(self) -> None:
        from app.jobs import get_runner
        from app.mcp.client import get_mcp_manager

        get_runner().bind_loop(asyncio.get_running_loop())
        self.refresh_sites()
        self.refresh_chats()
        recent = sessions.list_sessions(limit=1)
        if recent:
            await self.open_session(recent[0].id)
        else:
            await self.show_welcome()
        self.update_status()
        self.query_one("#prompt", Input).focus()
        self.run_worker(get_mcp_manager().sync(), group="mcp", exit_on_error=False)

    async def on_unmount(self) -> None:
        from app.mcp.client import get_mcp_manager

        if self.cancel is not None:
            self.cancel.set()
        await get_mcp_manager().shutdown()

    # ── sidebar ───────────────────────────────────────────────────────────

    def refresh_sites(self) -> None:
        sites = self.query_one("#sites", OptionList)
        sites.clear_options()
        sites.add_option(Option("All sites", id=ALL_SITES))
        for ws in get_catalog().list_workspaces():
            badge = {"ready": "[green]●[/]", "failed": "[red]●[/]"}.get(ws.status, "[yellow]●[/]")
            sites.add_option(Option(Text.from_markup(f"{badge} {escape(ws.name)} [dim]{ws.page_count}p[/]"), id=ws.id))

    def refresh_chats(self) -> None:
        chats = self.query_one("#chats", OptionList)
        chats.clear_options()
        for s in sessions.list_sessions(self.site_filter, limit=200):
            pin = "★ " if s.pinned else ""
            mode = "[magenta]agent[/]" if s.mode == "agent" else "[dim]rag[/]"
            chats.add_option(Option(Text.from_markup(f"{pin}{escape(s.title)}  {mode}"), id=s.id))
            if self.session and s.id == self.session.id:
                chats.highlighted = chats.option_count - 1

    @on(OptionList.OptionSelected, "#sites")
    def _site_picked(self, event: OptionList.OptionSelected) -> None:
        self.site_filter = None if event.option.id == ALL_SITES else event.option.id
        self.refresh_chats()
        self.notify(f"New chats will search {'every site' if not self.site_filter else event.option.prompt}.")

    @on(OptionList.OptionSelected, "#chats")
    async def _chat_picked(self, event: OptionList.OptionSelected) -> None:
        await self.open_session(event.option.id)
        self.query_one("#prompt", Input).focus()

    # ── chat log ──────────────────────────────────────────────────────────

    @property
    def chat(self) -> VerticalScroll:
        return self.query_one("#chat", VerticalScroll)

    async def show_welcome(self) -> None:
        await self.chat.remove_children()
        has_sites = bool(get_catalog().list_workspaces())
        hint = (
            "Ask a question below. Each answer cites the passages it used; the sources panel on the right shows them."
            if has_sites
            else "No sites yet. Index one with [b]/crawl https://docs.example.com site[/b], then ask away."
        )
        await self.chat.mount(Static(f"[b]Ask the site.[/b]\n\n{hint}\n\n[dim]F1 for keys and commands.[/]", classes="welcome"))

    async def open_session(self, session_id: str) -> None:
        self.session = sessions.require(session_id)
        self.query_one("#title", Label).update(escape(self.session.title))
        await self.chat.remove_children()
        turns = sessions.turns(session_id)
        if not turns:
            await self.show_welcome()
        for turn in turns:
            view = TurnView(turn["user"]["content"] if turn["user"] else "", turn["turn_id"])
            await self.chat.mount(view)
            await view.load(turn)
        last = next((t["answer"] for t in reversed(turns) if t.get("answer")), None)
        self.show_sources(last.get("citations") if last else [])
        self._last_usage = self.session.usage
        self.update_status()
        self.chat.scroll_end(animate=False)
        self.chat.anchor()

    def ensure_session(self) -> Session:
        if self.session is None:
            ids = [self.site_filter] if self.site_filter else []
            self.session = sessions.create_session(workspace_ids=ids)
        return self.session

    # ── sources inspector ─────────────────────────────────────────────────

    def show_sources(self, citations: Optional[Iterable[Dict[str, Any]]]) -> None:
        self._sources = list(citations or [])
        panel = self.query_one("#sources", OptionList)
        panel.clear_options()
        for c in self._sources:
            title = c.get("page_title") or c.get("source_url") or "source"
            panel.add_option(Option(Text.from_markup(
                f"[b][{c['marker']}][/b] {escape(title[:34])} [dim]{c.get('score', 0):.2f}[/]"
            )))
        detail = self.query_one("#source-detail", Static)
        detail.update("[dim]Highlight a source to see the passage.[/]" if self._sources else "[dim]No sources yet.[/]")

    @on(OptionList.OptionHighlighted, "#sources")
    def _source_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_index is None or event.option_index >= len(self._sources):
            return
        c = self._sources[event.option_index]
        lines = [f"[b]{escape(c.get('page_title') or '')}[/b]"]
        if c.get("heading"):
            lines.append(f"[dim]{escape(c['heading'])}[/]")
        url = c.get("source_url", "")
        # Textual markup needs the link target quoted (URLs contain ':').
        lines.append(f'[link="{url.replace(chr(34), "%22")}"]{escape(url)}[/link]')
        if c.get("workspace_name"):
            # Negative indexes mark whole-page reads, not chunks.
            chunk = f" · chunk #{c['chunk_index']}" if (c.get("chunk_index") or 0) >= 0 else ""
            lines.append(f"[dim]site: {escape(c['workspace_name'])}{chunk}[/]")
        lines.append("")
        snippet = re.sub(r"(^|\s)#{1,6}\s+", r"\1", c.get("snippet") or "")
        lines.append(escape(snippet))
        self.query_one("#source-detail", Static).update("\n".join(lines))

    # ── status line ───────────────────────────────────────────────────────

    def update_status(self, running: bool = False) -> None:
        s = self.session
        provider, model = (s.provider, s.model) if s else LLMManager.default_selection()
        thinking = (s.thinking or {}) if s else {}
        think = "off" if thinking.get("enabled") is False else (thinking.get("effort") or "on")
        sites = "all sites"
        if s and s.workspace_ids:
            names = [w.name for w in (get_catalog().get_workspace(i) for i in s.workspace_ids) if w]
            sites = ", ".join(names) or "all sites"
        parts = [
            f"[b]{escape(provider or '?')}[/b]:{escape(model or 'default')}",
            f"[magenta]{s.mode}[/]" if s and s.mode == "agent" else "rag",
            s.engine if s else "auto",
            f"top-k {s.top_k}" if s else "top-k 5",
            f"thinking {think}",
            escape(sites),
            format_tokens(self._last_usage),
        ]
        if running:
            parts.insert(0, "[yellow]● answering — Esc to stop[/]")
        self.query_one("#status", Static).update("  ·  ".join(p for p in parts if p))

    # ── asking ────────────────────────────────────────────────────────────

    @on(Input.Submitted, "#prompt")
    async def _submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            await self.handle_command(text)
        else:
            self.ask(text)

    @on(FollowUp.Picked)
    def _followup(self, event: FollowUp.Picked) -> None:
        self.ask(event.question)

    @work(exclusive=True, group="turn")
    async def ask(self, prompt: str, replace_turn_id: Optional[str] = None) -> None:
        session = self.ensure_session()
        if replace_turn_id:
            prompt = sessions.truncate_at_turn(session.id, replace_turn_id) if not prompt else prompt
            await self.open_session(session.id)
        if self.chat.query(".welcome"):
            await self.chat.remove_children(".welcome")

        view = TurnView(prompt)
        await self.chat.mount(view)
        self.chat.anchor()
        grounding: Optional[Dict[str, Any]] = None

        with runs.claim(session.id) as cancel:
            self.cancel = cancel
            self.update_status(running=True)
            try:
                async for name, data in TurnRunner(session.id, prompt, cancel=cancel).run():
                    step = view.current_step()
                    if name == "turn":
                        view.turn_id = data["turn_id"]
                    elif name == "notice":
                        await view.notice(data["message"])
                    elif name == "error":
                        await view.notice(data["message"], error=True)
                    elif name == "title":
                        self.query_one("#title", Label).update(escape(data["title"]))
                        self.refresh_chats()
                    elif name == "step":
                        await view.start_step(data["index"])
                    elif name == "thinking" and step:
                        await step.add_thinking(data["t"])
                    elif name == "token" and step:
                        await step.add_text(data["t"])
                    elif name == "tool_call" and step:
                        await step.add_tool(data["id"], data["name"], data["arguments"])
                    elif name == "tool_result":
                        block = view.tool_block(data["id"])
                        if block:
                            block.resolve(data)
                    elif name == "sources":
                        self.show_sources(data["citations"])
                    elif name == "usage":
                        self._last_usage = data
                        self.update_status(running=True)
                    elif name == "answer":
                        await view.finish()
                        self.show_sources(data["citations"])
                    elif name == "grounding":
                        grounding = data
                        view.set_meta([grounding_label(grounding)])
                    elif name == "followups":
                        await view.set_followups(data["questions"])
                    elif name == "done":
                        view.set_meta([
                            data["model"],
                            data["mode"],
                            f"{data['elapsed_ms'] / 1000:.1f}s",
                            format_tokens(data["usage"]),
                            grounding_label(grounding),
                            "[yellow]stopped[/]" if data.get("cancelled") else "",
                        ])
            finally:
                await view.finish()
                self.cancel = None
        self.session = sessions.require(session.id)
        self._last_usage = self.session.usage
        self.update_status()
        self.refresh_chats()

    # ── actions ───────────────────────────────────────────────────────────

    def action_stop(self) -> None:
        if self.cancel is not None:
            self.cancel.set()
            self.notify("Stopping…")

    async def action_new_chat(self, title: Optional[str] = None) -> None:
        ids = [self.site_filter] if self.site_filter else []
        self.session = sessions.create_session(workspace_ids=ids, title=title)
        self.query_one("#title", Label).update(escape(self.session.title))
        await self.show_welcome()
        self.show_sources([])
        self._last_usage = None
        self.refresh_chats()
        self.update_status()
        self.query_one("#prompt", Input).focus()

    def action_pick_model(self) -> None:
        current = (self.session.provider, self.session.model) if self.session else LLMManager.default_selection()

        def chosen(result) -> None:
            if result:
                self.set_model(*result)

        self.push_screen(ModelPicker(LLMManager.availability(), current), chosen)

    def set_model(self, provider: str, model: str) -> None:
        session = self.ensure_session()
        self.session = sessions.update_session(session.id, provider=provider, model=model)
        self.update_status()
        self.notify(f"Using {provider}:{model}")

    def action_toggle_mode(self) -> None:
        session = self.ensure_session()
        self.set_session(mode="rag" if session.mode == "agent" else "agent")

    def set_session(self, **fields: Any) -> None:
        session = self.ensure_session()
        try:
            self.session = sessions.update_session(session.id, **fields)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        self.update_status()
        self.refresh_chats()

    def action_retry(self) -> None:
        if self.session is None:
            return
        turns = sessions.turns(self.session.id)
        if not turns:
            self.notify("Nothing to retry yet.")
            return
        self.ask("", replace_turn_id=turns[-1]["turn_id"])

    def action_export(self, fmt: str = "md") -> None:
        if self.session is None:
            self.notify("No chat to export.")
            return
        kind = "json" if fmt == "json" else "markdown"
        text = sessions.export(self.session.id, kind)
        out = Path("exports")
        out.mkdir(exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in self.session.title).strip() or "chat"
        path = out / f"{safe}.{'json' if kind == 'json' else 'md'}"
        path.write_text(text, encoding="utf-8")
        self.notify(f"Exported to {path}")

    def action_toggle_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar")
        sidebar.display = not sidebar.display

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield SystemCommand("New chat", "Start a new conversation", self.action_new_chat)
        yield SystemCommand("Choose model", "Switch the model for this chat", self.action_pick_model)
        yield SystemCommand("Toggle agent mode", "Switch between rag and agent", self.action_toggle_mode)
        yield SystemCommand("Add a site", "Crawl and index a URL", lambda: self.open_crawl(""))
        yield SystemCommand("Search chats", "Full-text search over past chats", lambda: self.open_search(""))
        yield SystemCommand("Export chat", "Save this chat as Markdown", self.action_export)
        yield SystemCommand("Retry", "Ask the last question again", self.action_retry)
        yield SystemCommand("Help", "Keys and slash commands", self.action_help)

    def open_crawl(self, url: str, site: bool = False) -> None:
        def done(workspace_id) -> None:
            self.refresh_sites()
            if workspace_id:
                self.site_filter = workspace_id
                self.refresh_chats()

        self.push_screen(CrawlScreen(url, site), done)

    def open_search(self, query: str) -> None:
        async def done(session_id) -> None:
            if session_id:
                await self.open_session(session_id)
                self.refresh_chats()

        self.push_screen(SearchScreen(query), done)

    # ── slash commands ────────────────────────────────────────────────────

    async def handle_command(self, text: str) -> None:
        name, _, rest = text[1:].partition(" ")
        name, arg = name.lower(), rest.strip()

        if name in ("help", "?"):
            self.action_help()
        elif name == "new":
            await self.action_new_chat(arg or None)
        elif name == "model":
            if not arg:
                self.action_pick_model()
            elif ":" in arg:
                provider, model = arg.split(":", 1)
                try:
                    LLMManager.provider_class(provider)
                except ValueError as exc:
                    self.notify(str(exc), severity="error")
                    return
                self.set_model(provider, model)
            else:
                self.notify("Use /model provider:model, e.g. /model anthropic:claude-opus-5-5", severity="warning")
        elif name == "mode":
            if arg in ("rag", "agent"):
                self.set_session(mode=arg)
            else:
                self.action_toggle_mode()
        elif name == "engine":
            if arg in ENGINES:
                self.set_session(engine=arg)
            else:
                self.notify(f"Engine must be one of {', '.join(ENGINES)}", severity="warning")
        elif name == "topk":
            if arg.isdigit() and 1 <= int(arg) <= 20:
                self.set_session(top_k=int(arg))
            else:
                self.notify("top-k must be 1–20", severity="warning")
        elif name == "think":
            if arg in ("on", "off", ""):
                self.set_session(thinking={"enabled": arg != "off", "effort": None})
            elif arg in ("low", "medium", "high"):
                self.set_session(thinking={"enabled": True, "effort": arg})
            else:
                self.notify("Use /think on|off|low|medium|high", severity="warning")
        elif name == "site":
            await self._command_site(arg)
        elif name == "crawl":
            url, _, scope = arg.partition(" ")
            self.open_crawl(url, site=scope.strip() == "site")
        elif name == "search":
            self.open_search(arg)
        elif name == "rename" and arg:
            self.set_session(title=arg)
            self.query_one("#title", Label).update(escape(arg))
        elif name == "pin":
            self.set_session(pinned=not (self.session and self.session.pinned))
        elif name == "fork" and self.session:
            copy = sessions.fork(self.session.id)
            await self.open_session(copy.id)
            self.refresh_chats()
            self.notify("Forked into a new chat.")
        elif name == "retry":
            self.action_retry()
        elif name == "export":
            self.action_export(arg or "md")
        elif name == "delete" and self.session:
            sessions.delete_session(self.session.id)
            self.session = None
            await self.show_welcome()
            self.show_sources([])
            self.refresh_chats()
            self.update_status()
        else:
            self.notify(f"Unknown command /{name}. F1 lists them.", severity="warning")

    async def _command_site(self, arg: str) -> None:
        if not arg or arg == "all":
            self.set_session(workspace_ids=[])
            self.notify("This chat now searches every site.")
            return
        wanted = [a.strip().lower() for a in arg.split(",") if a.strip()]
        found = [w for w in get_catalog().list_workspaces() if w.id.lower() in wanted or w.name.lower() in wanted]
        if not found:
            self.notify(f"No site matching {arg!r}.", severity="error")
            return
        self.set_session(workspace_ids=[w.id for w in found])
        self.notify("This chat searches " + ", ".join(w.name for w in found))


def run() -> None:
    AskTheSiteApp().run()
