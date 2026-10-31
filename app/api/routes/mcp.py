"""External MCP servers the agent can use."""

from __future__ import annotations

import asyncio
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.catalog import MCPServerConfig, get_catalog, new_id
from app.mcp.client import get_mcp_manager

router = APIRouter(prefix="/mcp/servers", tags=["MCP"])

REDACTED = "•••"


class ServerFields(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    transport: Optional[Literal["stdio", "http"]] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    enabled: Optional[bool] = None


class NewServer(ServerFields):
    name: str = Field(..., min_length=1, max_length=64)
    transport: Literal["stdio", "http"] = "stdio"

    @model_validator(mode="after")
    def _target(self):
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio servers need a command")
        if self.transport == "http" and not self.url:
            raise ValueError("http servers need a url")
        return self


def _payload():
    status = get_mcp_manager().status()
    return {
        "servers": [
            s.to_dict() | {"status": status.get(s.id, {"connected": False, "error": None, "tools": []})}
            for s in get_catalog().list_mcp_servers()
        ]
    }


def _require(server_id: str) -> MCPServerConfig:
    cfg = get_catalog().get_mcp_server(server_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"No MCP server with id {server_id!r}")
    return cfg


def _keep_secrets(new: Dict[str, str], old: Dict[str, str]) -> Dict[str, str]:
    """The UI only ever sees redacted values; sending one back means 'unchanged'."""
    return {k: (old.get(k, "") if v == REDACTED else v) for k, v in new.items()}


@router.get("")
async def list_servers():
    return _payload()


@router.post("", status_code=201)
async def add_server(body: NewServer):
    catalog = get_catalog()
    if any(s.name == body.name for s in catalog.list_mcp_servers()):
        raise HTTPException(status_code=409, detail=f"An MCP server named {body.name!r} already exists")
    cfg = MCPServerConfig(
        id=new_id(),
        name=body.name,
        transport=body.transport,
        command=body.command,
        args=body.args or [],
        env=body.env or {},
        url=body.url,
        headers=body.headers or {},
        enabled=True if body.enabled is None else body.enabled,
    )
    catalog.create_mcp_server(cfg)
    await get_mcp_manager().sync()
    return _payload()


@router.patch("/{server_id}")
async def update_server(server_id: str, body: ServerFields):
    old = _require(server_id)
    fields = body.model_dump(exclude_unset=True)
    if "env" in fields:
        fields["env"] = _keep_secrets(fields["env"] or {}, old.env)
    if "headers" in fields:
        fields["headers"] = _keep_secrets(fields["headers"] or {}, old.headers)
    get_catalog().update_mcp_server(server_id, **fields)
    await get_mcp_manager().sync()
    return _payload()


@router.delete("/{server_id}")
async def delete_server(server_id: str):
    _require(server_id)
    get_catalog().delete_mcp_server(server_id)
    await get_mcp_manager().sync()
    return _payload()


@router.post("/{server_id}/test")
async def test_server(server_id: str):
    """Connect once and list the server's tools, without enabling it."""
    cfg = _require(server_id)
    try:
        tools = await get_mcp_manager().test(cfg)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not connect: {exc}") from exc
    return {"ok": True, "tools": tools}


@router.post("/reconnect")
async def reconnect():
    """Retry every enabled server (e.g. after starting a local one)."""
    manager = get_mcp_manager()
    await manager.shutdown()
    await asyncio.shield(manager.sync())
    return _payload()
