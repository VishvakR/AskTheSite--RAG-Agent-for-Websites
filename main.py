"""
AskTheSite CLI.

    uv run main.py crawl https://docs.crawl4ai.com --mode site --max-pages 25
    uv run main.py ask <workspace-id> "How does crawl4ai extract markdown?"
    uv run main.py compare <workspace-id> "chunking strategy"
    uv run main.py list
    uv run main.py mcp          # serve the indexed sites to MCP clients over stdio
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from dotenv import load_dotenv

from app.catalog import get_catalog
from app.config import get_settings
from app.index.retrieval import compare
from app.jobs import get_runner
from app.logger import Logger
from app.services import workspaces as ws_service

load_dotenv()
logger = logging.getLogger("askthesite")


async def cmd_crawl(args) -> int:
    get_runner().bind_loop(asyncio.get_running_loop())
    ws = ws_service.create_workspace(
        seed_url=args.url,
        name=args.name,
        mode=args.mode,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
    )
    print(f"workspace: {ws.id}")

    job = ws_service.start_build(ws.id)
    last = None
    async for message in get_runner().subscribe(job.id):
        if message["event"] == "progress":
            d = message["data"]
            line = f"  [{d['status']}] {d.get('phase','')} {d.get('message','')}"
            if line != last:
                print(line)
                last = line
        elif message["event"] == "end":
            break

    final = get_catalog().get_job(job.id)
    if final and final.status == "succeeded":
        print(f"done: {final.result}")
        return 0
    print(f"failed: {final.error if final else 'unknown error'}", file=sys.stderr)
    return 1


def cmd_ask(args) -> int:
    ws = ws_service.require(args.workspace_id)
    agent = ws_service.build_agent(ws, engine=args.engine, top_k=args.top_k)
    for event, payload in agent.stream(args.question):
        if event == "sources":
            for c in payload["citations"]:
                print(f"  [{c['marker']}] {c['score']:.3f}  {c['page_title']}  {c['source_url']}")
            print()
        elif event == "token":
            sys.stdout.write(payload["t"])
            sys.stdout.flush()
        elif event == "done":
            print(f"\n\n({payload['elapsed_ms']}ms, {payload['model']})")
        elif event == "error":
            print(f"\nerror: {payload['message']}", file=sys.stderr)
            return 1
    return 0


def cmd_compare(args) -> int:
    ws = ws_service.require(args.workspace_id)
    out = compare(ws.collection_name, ws.index_version, args.question, args.top_k)
    for name, res in out["strategies"].items():
        print(f"\n{name}  ({res['elapsed_ms']}ms){'  error: ' + res['error'] if res['error'] else ''}")
        for r in res["results"]:
            print(f"  {r['score']:.3f}  {r['page_title'][:28]:<28} {r['snippet'][:60]}")
    o = out["overlap"]
    print(f"\nagreement: {o['agreement']} ({o['shared_count']} shared / {o['union_count']} union)")
    return 0


def cmd_list(args) -> int:
    rows = ws_service.list_workspaces()
    if not rows:
        print("no workspaces yet")
        return 0
    for w in rows:
        print(f"{w.id:<34} {w.status:<9} {w.page_count:>4}p {w.chunk_count:>6}c  {w.seed_url}")
    return 0


def cmd_delete(args) -> int:
    ws_service.delete_workspace(args.workspace_id)
    print(f"deleted {args.workspace_id}")
    return 0


def cmd_mcp(args) -> int:
    from app.mcp.server import get_server

    # stdout carries the MCP protocol; logging already goes to stderr.
    get_server().run("stdio")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="askthesite", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("crawl", help="Create a workspace and index a site")
    c.add_argument("url")
    c.add_argument("--name")
    c.add_argument("--mode", choices=["page", "site"], default="page")
    c.add_argument("--max-pages", type=int)
    c.add_argument("--max-depth", type=int)
    c.set_defaults(func=cmd_crawl, is_async=True)

    a = sub.add_parser("ask", help="Ask a question against a workspace")
    a.add_argument("workspace_id")
    a.add_argument("question")
    a.add_argument("--engine", choices=["auto", "bm25", "rerank"], default="auto")
    a.add_argument("--top-k", type=int, default=5)
    a.set_defaults(func=cmd_ask, is_async=False)

    m = sub.add_parser("compare", help="Compare all three retrieval strategies")
    m.add_argument("workspace_id")
    m.add_argument("question")
    m.add_argument("--top-k", type=int, default=5)
    m.set_defaults(func=cmd_compare, is_async=False)

    l = sub.add_parser("list", help="List workspaces")
    l.set_defaults(func=cmd_list, is_async=False)

    d = sub.add_parser("delete", help="Delete a workspace")
    d.add_argument("workspace_id")
    d.set_defaults(func=cmd_delete, is_async=False)

    s = sub.add_parser("mcp", help="Serve indexed sites to MCP clients over stdio")
    s.set_defaults(func=cmd_mcp, is_async=False)

    return p


def main() -> int:
    args = build_parser().parse_args()
    Logger.setup(get_settings().log_level)
    if args.is_async:
        return asyncio.run(args.func(args))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
