"""
AskTheSite as an MCP client: external MCP servers' tools, usable by the agent.

Each enabled row in ``mcp_servers`` gets one long-lived connection. A
connection is owned by its own asyncio task, because the MCP client's anyio
task groups must be entered and exited from the same task; other tasks just
call tools through it. Tools are exposed to the agent as
``mcp__<server>__<tool>`` so they can't collide with built-ins.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from mcp import Client
from mcp.client.stdio import StdioServerParameters, get_default_environment
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from app.agent.tools import EXTERNAL_SOURCES, Tool, ToolContext, ToolResult
from app.catalog import MCPServerConfig, get_catalog

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_S = 20.0
_UNSAFE = re.compile(r"[^a-zA-Z0-9_-]+")


def tool_name(server: str, tool: str) -> str:
    # Provider limits: [a-zA-Z0-9_-], at most 64 characters.
    name = f"mcp__{_UNSAFE.sub('_', server)}__{_UNSAFE.sub('_', tool)}"
    return name[:64]


def _text_of(result: Any) -> str:
    parts: List[str] = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
        else:
            parts.append(f"[{getattr(block, 'type', 'content')} omitted]")
    if not parts and getattr(result, "structured_content", None) is not None:
        import json

        parts.append(json.dumps(result.structured_content))
    return "\n".join(parts) or "(no output)"


class Connection:
    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.client: Optional[Client] = None
        self.tools: List[Any] = []
        self.error: Optional[str] = None
        self._ready = asyncio.Event()
        self._close = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    def _target(self):
        cfg = self.config
        if cfg.transport == "stdio":
            if not cfg.command:
                raise ValueError("a stdio server needs a command")
            env = get_default_environment() | dict(cfg.env)
            return StdioServerParameters(command=cfg.command, args=list(cfg.args), env=env)
        if not cfg.url:
            raise ValueError("an http server needs a url")
        if cfg.headers:
            return streamable_http_client(cfg.url, http_client=create_mcp_http_client(headers=dict(cfg.headers)))
        return cfg.url

    async def _main(self) -> None:
        try:
            async with Client(self._target(), read_timeout_seconds=120) as client:
                self.client = client
                tools: List[Any] = []
                cursor = None
                while True:
                    page = await client.list_tools(cursor=cursor)
                    tools.extend(page.tools)
                    cursor = page.next_cursor
                    if not cursor:
                        break
                self.tools = tools
                self._ready.set()
                await self._close.wait()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # anyio wraps failures in exception groups
            self.error = f"{exc.__class__.__name__}: {exc}"
            logger.warning("MCP server %s failed: %s", self.config.name, self.error)
        finally:
            self.client = None
            self._ready.set()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._main(), name=f"mcp:{self.config.name}")
        try:
            await asyncio.wait_for(self._ready.wait(), CONNECT_TIMEOUT_S)
        except asyncio.TimeoutError:
            self.error = f"timed out connecting after {CONNECT_TIMEOUT_S:.0f}s"
            await self.stop()
        if self.error:
            raise RuntimeError(self.error)

    async def stop(self) -> None:
        self._close.set()
        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()

    @property
    def connected(self) -> bool:
        return self.client is not None

    async def call(self, name: str, arguments: Dict[str, Any], timeout: float) -> ToolResult:
        if self.client is None:
            return ToolResult.error(f"MCP server {self.config.name!r} is not connected")
        result = await self.client.call_tool(name, arguments, read_timeout_seconds=timeout)
        return ToolResult(content=_text_of(result), is_error=bool(result.is_error))

    def as_tools(self) -> List[Tool]:
        out: List[Tool] = []
        for spec in self.tools:
            remote = spec.name

            async def handler(ctx: ToolContext, args: Dict[str, Any], _remote=remote) -> ToolResult:
                timeout = ctx.settings.tool_timeout_s if ctx.settings else 60.0
                return await self.call(_remote, args, timeout)

            out.append(Tool(
                name=tool_name(self.config.name, remote),
                description=f"[{self.config.name}] {spec.description or spec.title or remote}",
                handler=handler,
                input_schema=spec.input_schema or {"type": "object", "properties": {}},
                source=f"mcp:{self.config.name}",
                risk="external",
            ))
        return out


class MCPClientManager:
    def __init__(self) -> None:
        self._connections: Dict[str, Connection] = {}
        self._lock: Optional[asyncio.Lock] = None

    def _guard(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def sync(self) -> None:
        """Connect newly enabled servers, drop removed ones, restart edited ones."""
        async with self._guard():
            wanted = {c.id: c for c in get_catalog().list_mcp_servers(enabled_only=True)}
            for server_id, conn in list(self._connections.items()):
                cfg = wanted.get(server_id)
                if cfg is None or cfg.updated_at != conn.config.updated_at or not conn.connected:
                    await conn.stop()
                    del self._connections[server_id]
            for server_id, cfg in wanted.items():
                if server_id in self._connections:
                    continue
                conn = Connection(cfg)
                self._connections[server_id] = conn
                try:
                    await conn.start()
                except Exception:
                    pass  # recorded on conn.error and reported by status()

    async def test(self, config: MCPServerConfig) -> List[Dict[str, Any]]:
        """Connect once, list tools, disconnect -- for the 'Test' button."""
        conn = Connection(config)
        try:
            await conn.start()
            return [{"name": t.name, "description": t.description} for t in conn.tools]
        finally:
            await conn.stop()

    def tools(self) -> List[Tool]:
        return [t for conn in self._connections.values() if conn.connected for t in conn.as_tools()]

    def status(self) -> Dict[str, Dict[str, Any]]:
        return {
            server_id: {
                "connected": conn.connected,
                "error": conn.error,
                "tools": [t.name for t in conn.tools] if conn.connected else [],
            }
            for server_id, conn in self._connections.items()
        }

    async def shutdown(self) -> None:
        async with self._guard():
            for conn in self._connections.values():
                await conn.stop()
            self._connections.clear()


_manager: Optional[MCPClientManager] = None


def get_mcp_manager() -> MCPClientManager:
    global _manager
    if _manager is None:
        _manager = MCPClientManager()
        EXTERNAL_SOURCES.append(_manager.tools)
    return _manager
