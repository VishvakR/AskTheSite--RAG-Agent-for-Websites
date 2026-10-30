"""Health, model selection and the tool catalogue."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent import tools as tool_catalogue
from app.catalog import get_catalog
from app.llm import LLMManager
from app.services import workspaces as ws_service

router = APIRouter()

VERSION = "0.3.0"


class ModelPatch(BaseModel):
    enabled: Optional[bool] = None
    is_default: Optional[bool] = None


class CustomModel(BaseModel):
    provider: str
    model_id: str = Field(..., min_length=1, max_length=200)
    make_default: bool = False


class ToolPatch(BaseModel):
    enabled: bool


@router.get("/health", tags=["Utility"])
async def health_check():
    from app.mcp.client import get_mcp_manager

    providers = LLMManager.availability()
    mcp = get_mcp_manager().status()
    return {
        "status": "ok",
        "service": "AskTheSite API",
        "version": VERSION,
        "workspaces": len(ws_service.list_workspaces()),
        "llm_ready": any(p["available"] for p in providers),
        "mcp_connected": sum(1 for s in mcp.values() if s["connected"]),
    }


# ── models ────────────────────────────────────────────────────────────────


def _models_payload():
    provider, model = LLMManager.default_selection()
    return {
        "providers": LLMManager.availability(),
        "default": provider,
        "default_model": model,
    }


@router.get("/models", tags=["Models"])
async def list_models():
    """Every provider, whether it's usable right now (and why not), and its models."""
    return _models_payload()


@router.post("/models", status_code=201, tags=["Models"])
async def add_model(body: CustomModel):
    """Make a model selectable that the provider doesn't list (e.g. a new release)."""
    try:
        LLMManager.provider_class(body.provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    get_catalog().upsert_model_setting(
        body.provider, body.model_id, enabled=True, is_default=body.make_default or None
    )
    return _models_payload()


@router.patch("/models/{provider}/{model_id:path}", tags=["Models"])
async def update_model(provider: str, model_id: str, body: ModelPatch):
    """Enable or hide a model, or make it the default for new chats."""
    try:
        LLMManager.provider_class(provider)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    get_catalog().upsert_model_setting(
        provider, model_id, enabled=body.enabled, is_default=body.is_default
    )
    return _models_payload()


@router.delete("/models/{provider}/{model_id:path}", tags=["Models"])
async def reset_model(provider: str, model_id: str):
    """Forget a model's settings (and remove it, if it was added by hand)."""
    get_catalog().delete_model_setting(provider, model_id)
    return _models_payload()


# ── tools ─────────────────────────────────────────────────────────────────


@router.get("/tools", tags=["Tools"])
async def list_tools():
    return {"tools": tool_catalogue.describe_all()}


@router.patch("/tools/{name}", tags=["Tools"])
async def update_tool(name: str, body: ToolPatch):
    try:
        tool_catalogue.set_enabled(name, body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"tools": tool_catalogue.describe_all()}
