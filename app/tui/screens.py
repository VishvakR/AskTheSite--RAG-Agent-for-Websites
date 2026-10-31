"""Modal screens: model picker, add-a-site, search, help."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, ProgressBar, RadioButton, RadioSet, Static
from textual.widgets.option_list import Option

HELP = """\
[b]Asking[/b]
  Enter            send          Esc        stop the answer
  ctrl+n           new chat      ctrl+r     retry last question
  ctrl+o           pick model    ctrl+t     switch rag ↔ agent
  ctrl+b           sidebar       ctrl+s     export chat to Markdown
  ctrl+p           command palette        ctrl+q     quit

[b]Slash commands[/b]
  /new [title]             start a chat (on the selected site)
  /model [provider:model]  pick or set the model
  /mode rag|agent          single-pass retrieval or tool-using agent
  /engine auto|bm25|rerank retrieval strategy
  /topk N                  passages per search
  /think on|off|low|medium|high
  /site <name|id|all>      which sites this chat searches
  /crawl <url> [site]      index a new page or whole site
  /search <words>          search every past chat
  /rename <title>  /fork  /retry  /export [md|json]  /delete  /help
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("AskTheSite — keys & commands", classes="dialog-title")
            yield Static(HELP)
            yield Button("Close", id="close", variant="primary")

    @on(Button.Pressed, "#close")
    def _close(self) -> None:
        self.dismiss(None)


class ModelPicker(ModalScreen[Optional[Tuple[str, str]]]):
    """Every enabled model, grouped by provider, with what it can do."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, providers: List[Dict[str, Any]], current: Tuple[Optional[str], Optional[str]]):
        super().__init__()
        self.providers = providers
        self.current = current

    def compose(self) -> ComposeResult:
        options: List[Option] = []
        highlight = None
        for p in self.providers:
            status = "" if p["available"] else f"  — {p['reason']}"
            options.append(Option(Text.from_markup(f"[b]{escape(p['label'])}[/b][dim]{escape(status)}[/]"), disabled=True))
            for spec in p["specs"]:
                if not spec.get("enabled", True):
                    continue
                caps = " ".join(
                    tag for tag, on_ in (("tools", spec["supports_tools"]), ("thinking", spec["supports_thinking"]), ("vision", spec["supports_vision"])) if on_
                )
                mark = "●" if (p["provider"], spec["id"]) == self.current else " "
                label = Text.from_markup(
                    f" {mark} {escape(spec['label'])}  [dim]{escape(caps)}[/]"
                    + ("" if p["available"] else "  [red]unavailable[/]")
                )
                if (p["provider"], spec["id"]) == self.current:
                    highlight = len(options)
                options.append(Option(label, id=f"{p['provider']}\x00{spec['id']}", disabled=not p["available"]))
        with Vertical(classes="dialog"):
            yield Label("Choose a model", classes="dialog-title")
            yield OptionList(*options, id="models")
            yield Label("[dim]Enter to choose · Esc to cancel · add more under /models in the web UI[/]")
        self._highlight = highlight

    def on_mount(self) -> None:
        if self._highlight is not None:
            self.query_one(OptionList).highlighted = self._highlight

    @on(OptionList.OptionSelected)
    def _picked(self, event: OptionList.OptionSelected) -> None:
        provider, model = event.option.id.split("\x00", 1)
        self.dismiss((provider, model))


class CrawlScreen(ModalScreen[Optional[str]]):
    """Index a new site, with live progress from the job runner."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Close")]

    def __init__(self, url: str = "", site: bool = False):
        super().__init__()
        self.url = url
        self.site = site
        self.workspace_id: Optional[str] = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Add a site", classes="dialog-title")
            yield Input(self.url, placeholder="https://docs.example.com", id="url")
            with RadioSet(id="mode"):
                yield RadioButton("Just this page", value=not self.site)
                yield RadioButton("Whole site (up to 100 pages)", value=self.site)
            yield ProgressBar(total=None, show_eta=False, id="progress")
            yield Static("", id="status")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Crawl", id="go", variant="primary")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        self.query_one("#progress").display = False
        if self.url:
            self.query_one("#go", Button).press()

    @on(Button.Pressed, "#close")
    def _close(self) -> None:
        self.dismiss(self.workspace_id)

    @on(Input.Submitted, "#url")
    def _submit(self) -> None:
        self.query_one("#go", Button).press()

    @on(Button.Pressed, "#go")
    def _go(self) -> None:
        url = self.query_one("#url", Input).value.strip()
        if not url.startswith(("http://", "https://")):
            self.query_one("#status", Static).update("[red]Enter a full http(s) URL.[/]")
            return
        mode = "site" if self.query_one(RadioSet).pressed_index == 1 else "page"
        self.query_one("#go", Button).disabled = True
        self._crawl(url, mode)

    @work(exclusive=True)
    async def _crawl(self, url: str, mode: str) -> None:
        from app.catalog import get_catalog
        from app.jobs import get_runner
        from app.services import workspaces as ws_service

        status = self.query_one("#status", Static)
        bar = self.query_one("#progress", ProgressBar)
        bar.display = True
        try:
            ws = ws_service.create_workspace(seed_url=url, mode=mode)
        except ValueError as exc:
            status.update(f"[red]{escape(str(exc))}[/]")
            self.query_one("#go", Button).disabled = False
            return
        self.workspace_id = ws.id
        job = ws_service.start_build(ws.id)
        async for message in get_runner().subscribe(job.id):
            if message["event"] == "progress":
                d = message["data"]
                if d.get("total"):
                    bar.update(total=d["total"], progress=d.get("current", 0))
                status.update(escape(f"{d.get('phase', '')} {d.get('message', '')}".strip()))
            elif message["event"] == "end":
                break
        final = get_catalog().get_job(job.id)
        ws = get_catalog().get_workspace(ws.id)
        if final and final.status == "succeeded":
            status.update(f"[green]Ready:[/] {escape(ws.name)} — {ws.page_count} pages, {ws.chunk_count} chunks")
        else:
            status.update(f"[red]Failed:[/] {escape(final.error if final else 'unknown error')}")
        self.query_one("#close", Button).label = "Done"


class SearchScreen(ModalScreen[Optional[str]]):
    """Full-text search over every past chat; returns the chosen session id."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Close")]

    def __init__(self, query: str = ""):
        super().__init__()
        self.initial = query

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Search chats", classes="dialog-title")
            yield Input(self.initial, placeholder="Words from a question or answer…", id="q")
            yield OptionList(id="hits")

    def on_mount(self) -> None:
        if self.initial:
            self._search(self.initial)

    @on(Input.Changed, "#q")
    def _changed(self, event: Input.Changed) -> None:
        self._search(event.value)

    def _search(self, query: str) -> None:
        from app.services import sessions

        hits = self.query_one("#hits", OptionList)
        hits.clear_options()
        if len(query.strip()) < 2:
            return
        for h in sessions.search(query, limit=30):
            label = Text.from_markup(f"[b]{escape(h['title'])}[/b]  [dim]{h['role']}[/]\n  {escape(h['snippet'])}")
            hits.add_option(Option(label, id=f"{h['session_id']}\x00{h['message_id']}"))

    @on(OptionList.OptionSelected, "#hits")
    def _picked(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id.split("\x00", 1)[0])
