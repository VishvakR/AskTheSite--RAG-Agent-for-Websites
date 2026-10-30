"""
The tools AskTheSite's agent can call.

Each one is a thin, typed wrapper over code the rest of the app already uses
(retrieval, the page store, the crawl manifest), so the agent sees exactly
what the Retrieval Lab and the Documents tab see. The same functions back the
MCP server, so external clients get identical behaviour.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urldefrag

from pydantic import BaseModel, Field

from app.agent.search import citation_for, format_hit, search_workspaces
from app.agent.tools.base import BUILTIN, ToolContext, ToolResult

Engine = Literal["auto", "bm25", "rerank"]


def _norm(url: str) -> str:
    return urldefrag(url)[0].rstrip("/")


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n\n[… truncated, {len(text) - limit} more characters]"


def _ready(ctx: ToolContext) -> List[Any]:
    return [ws for ws in ctx.workspaces if ws.chunk_count > 0]


# ── search_site ───────────────────────────────────────────────────────────


class SearchArgs(BaseModel):
    query: str = Field(..., min_length=1, description="What to look for. Rephrase and search again if results are thin.")
    workspace: Optional[str] = Field(None, description="Limit to one site, by workspace id or name. Omit to search every site in this chat.")
    engine: Optional[Engine] = Field(None, description="auto = semantic, bm25 = exact keywords, rerank = most precise but slowest.")
    top_k: Optional[int] = Field(None, ge=1, le=20, description="How many passages to return.")


@BUILTIN.tool(
    "search_site",
    "Search the indexed website content and return the most relevant passages, "
    "each with a citation number like [3]. Cite those numbers in your answer.",
    args=SearchArgs,
)
def search_site(ctx: ToolContext, args: SearchArgs) -> ToolResult:
    targets = _ready(ctx)
    if args.workspace:
        ws = ctx.workspace(args.workspace)
        if ws is None:
            names = ", ".join(f"{w.name} ({w.id})" for w in ctx.workspaces) or "none"
            return ToolResult.error(f"no site called {args.workspace!r}. Available: {names}")
        targets = [ws]
    if not targets:
        return ToolResult.error("no indexed sites are available in this chat yet")

    hits, errors = search_workspaces(
        targets, args.query, args.engine or ctx.engine, args.top_k or ctx.top_k
    )
    blocks, cited = [], []
    for ws, chunk in hits:
        citation = ctx.ledger.add(citation_for(ws, chunk))
        cited.append(citation)
        blocks.append(format_hit(citation["marker"], chunk))

    if not blocks:
        note = f" ({'; '.join(errors)})" if errors else ""
        return ToolResult(
            content=f"No passages matched {args.query!r}{note}. Try different wording or engine='bm25' for exact terms.",
            data={"citations": []},
        )
    return ToolResult(
        content="\n\n---\n\n".join(blocks),
        data={"citations": cited, "errors": errors},
    )


# ── read_page ─────────────────────────────────────────────────────────────


class ReadPageArgs(BaseModel):
    url: str = Field(..., description="URL of a crawled page, e.g. one from a search result.")
    max_chars: int = Field(6000, ge=500, le=40000, description="Truncate long pages to this many characters.")


def find_page(workspaces: List[Any], url: str):
    """Locate a crawled page by URL across *workspaces*: ``(ws, meta, markdown)``."""
    from app.config import get_settings
    from app.crawler.pages import WorkspaceStore

    wanted = _norm(url)
    for ws in workspaces:
        store = WorkspaceStore(get_settings().workspace_dir(ws.id))
        manifest = store.read_manifest() or {}
        for page in manifest.get("pages", []):
            if page.get("file") and _norm(page.get("url", "")) == wanted:
                path = store.root / page["file"]
                if path.exists():
                    meta, body = store.read_page(path)
                    return ws, meta, body
    return None


@BUILTIN.tool(
    "read_page",
    "Read the full text of one crawled page. Use it when a search passage is cut "
    "off or you need the surrounding context.",
    args=ReadPageArgs,
)
def read_page(ctx: ToolContext, args: ReadPageArgs) -> ToolResult:
    found = find_page(ctx.workspaces, args.url)
    if found is None:
        return ToolResult.error(f"{args.url} is not a crawled page in this chat's sites")
    ws, meta, body = found
    citation = ctx.ledger.add({
        "chunk_id": None,
        "source_url": meta.get("url", args.url),
        "page_title": meta.get("title", ""),
        "heading": "Full page",
        "chunk_index": -1,
        "score": 1.0,
        "rank": 0,
        "page_id": meta.get("page_id", ""),
        "snippet": " ".join(body.split())[:320],
        "workspace_id": ws.id,
        "workspace_name": ws.name,
    })
    header = f"[{citation['marker']}] {meta.get('title') or args.url}\nURL: {meta.get('url', args.url)}\n\n"
    return ToolResult(
        content=header + _truncate(body, args.max_chars),
        data={"citations": [citation]},
    )


# ── list_pages ────────────────────────────────────────────────────────────


class ListPagesArgs(BaseModel):
    contains: Optional[str] = Field(None, description="Only pages whose title or URL contains this text.")
    workspace: Optional[str] = Field(None, description="Workspace id or name; omit for all sites in this chat.")
    limit: int = Field(40, ge=1, le=200)


@BUILTIN.tool(
    "list_pages",
    "List crawled pages (title, URL, link depth from the start page). Useful to see "
    "what a site covers or to find a page to read.",
    args=ListPagesArgs,
)
def list_pages(ctx: ToolContext, args: ListPagesArgs) -> ToolResult:
    from app.config import get_settings
    from app.crawler.pages import WorkspaceStore

    targets = [ctx.workspace(args.workspace)] if args.workspace else ctx.workspaces
    if args.workspace and targets[0] is None:
        return ToolResult.error(f"no site called {args.workspace!r}")

    needle = (args.contains or "").lower()
    rows: List[Dict[str, Any]] = []
    for ws in targets:
        manifest = WorkspaceStore(get_settings().workspace_dir(ws.id)).read_manifest() or {}
        for page in manifest.get("pages", []):
            if page.get("error"):
                continue
            text = f"{page.get('title', '')} {page.get('url', '')}".lower()
            if needle and needle not in text:
                continue
            rows.append({"site": ws.name, "title": page.get("title", ""), "url": page.get("url", ""), "depth": page.get("depth", 0)})
    total = len(rows)
    rows = sorted(rows, key=lambda r: (r["depth"], r["url"]))[: args.limit]
    lines = [f"- {r['title'] or '(untitled)'} — {r['url']} (depth {r['depth']}, {r['site']})" for r in rows]
    more = f"\n… and {total - len(rows)} more" if total > len(rows) else ""
    return ToolResult(content=("\n".join(lines) or "No matching pages.") + more, data={"pages": rows, "total": total})


# ── list_workspaces ───────────────────────────────────────────────────────


class NoArgs(BaseModel):
    pass


@BUILTIN.tool(
    "list_workspaces",
    "List the websites available in this chat with their page and chunk counts.",
    args=NoArgs,
)
def list_workspaces(ctx: ToolContext, args: NoArgs) -> ToolResult:
    rows = [
        {"id": w.id, "name": w.name, "seed_url": w.seed_url, "status": w.status,
         "pages": w.page_count, "chunks": w.chunk_count}
        for w in ctx.workspaces
    ]
    lines = [f"- {r['name']} (id {r['id']}): {r['seed_url']} — {r['pages']} pages, {r['chunks']} chunks, {r['status']}" for r in rows]
    return ToolResult(content="\n".join(lines) or "No sites in this chat.", data={"workspaces": rows})


# ── compare_retrieval ─────────────────────────────────────────────────────


class CompareArgs(BaseModel):
    query: str = Field(..., min_length=1)
    workspace: Optional[str] = Field(None, description="Workspace id or name; defaults to the first site.")
    top_k: int = Field(5, ge=1, le=20)


@BUILTIN.tool(
    "compare_retrieval",
    "Run one query through all three retrieval strategies (semantic, keyword, "
    "rerank) and report how much they agree. Use when results seem off or the "
    "user asks why something was or wasn't found.",
    args=CompareArgs,
)
def compare_retrieval(ctx: ToolContext, args: CompareArgs) -> ToolResult:
    from app.index.retrieval import compare

    ws = ctx.workspace(args.workspace) if args.workspace else (_ready(ctx) or [None])[0]
    if ws is None:
        return ToolResult.error("no indexed site to compare on")
    out = compare(ws.collection_name, ws.index_version, args.query, args.top_k)
    lines = [f"Site: {ws.name}"]
    for name, res in out["strategies"].items():
        top = ", ".join(f"{r['page_title'] or r['source_url']} ({r['score']:.2f})" for r in res["results"][:3])
        lines.append(f"- {name} ({res['elapsed_ms']}ms): {top or 'nothing'}{' — error: ' + res['error'] if res['error'] else ''}")
    overlap = out["overlap"]
    lines.append(f"Agreement: {overlap['agreement']} ({overlap['shared_count']} shared of {overlap['union_count']})")
    return ToolResult(content="\n".join(lines), data=out)


# ── fetch_url (opt-in) ────────────────────────────────────────────────────


class FetchArgs(BaseModel):
    url: str = Field(..., description="An http(s) URL to fetch live.")
    max_chars: int = Field(6000, ge=500, le=40000)


@BUILTIN.tool(
    "fetch_url",
    "Fetch a live web page that is not in the index (e.g. a link a crawled page "
    "points to). Slower than search; use sparingly.",
    args=FetchArgs,
    enabled_by_default=False,
    risk="network",
)
async def fetch_url(ctx: ToolContext, args: FetchArgs) -> ToolResult:
    from app.crawler.main import WebCrawler
    from app.crawler.pages import WorkspaceStore

    if not args.url.startswith(("http://", "https://")):
        return ToolResult.error("only http(s) URLs can be fetched")
    with tempfile.TemporaryDirectory(prefix="askthesite-fetch-") as tmp:
        records = await WebCrawler().crawl_page(args.url, Path(tmp))
        record = next((r for r in records if r.ok), None)
        if record is None:
            reason = records[0].error if records else "unknown error"
            return ToolResult.error(f"could not fetch {args.url}: {reason}")
        meta, body = WorkspaceStore(Path(tmp)).read_page(Path(tmp) / record.file)
    citation = ctx.ledger.add({
        "chunk_id": None, "source_url": args.url, "page_title": meta.get("title", ""),
        "heading": "Live fetch", "chunk_index": -2, "score": 1.0, "rank": 0, "page_id": "",
        "snippet": " ".join(body.split())[:320],
    })
    header = f"[{citation['marker']}] {meta.get('title') or args.url} (live)\nURL: {args.url}\n\n"
    return ToolResult(content=header + _truncate(body, args.max_chars), data={"citations": [citation]})
