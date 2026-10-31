"""
The tool catalogue: built-ins plus anything an external source (MCP) adds,
filtered by the switches the user set in Settings.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List

from app.agent.tools.base import BUILTIN, Tool, ToolContext, ToolRegistry, ToolResult
from app.agent.tools import builtin as _builtin  # noqa: F401  (registers the tools)

logger = logging.getLogger(__name__)

_OVERRIDES_KEY = "tool_overrides"

#: Callables returning extra tools (MCP registers one). Kept as hooks so this
#: module never imports the MCP client.
EXTERNAL_SOURCES: List[Callable[[], List[Tool]]] = []


def _overrides() -> Dict[str, bool]:
    from app.catalog import get_catalog

    try:
        return get_catalog().get_setting(_OVERRIDES_KEY, {}) or {}
    except Exception:
        logger.debug("Tool overrides unavailable", exc_info=True)
        return {}


def _default_enabled(tool: Tool) -> bool:
    from app.config import get_settings

    if tool.name == "fetch_url":
        return get_settings().agent_allow_fetch
    return tool.enabled_by_default


def all_tools() -> List[Tool]:
    tools = list(BUILTIN.all())
    for source in EXTERNAL_SOURCES:
        try:
            tools.extend(source())
        except Exception:
            logger.exception("A tool source failed; continuing without it")
    return tools


def is_enabled(tool: Tool, overrides: Dict[str, bool] | None = None) -> bool:
    overrides = _overrides() if overrides is None else overrides
    return overrides.get(tool.name, _default_enabled(tool))


def enabled_tools() -> List[Tool]:
    overrides = _overrides()
    return [t for t in all_tools() if is_enabled(t, overrides)]


def describe_all() -> List[dict]:
    overrides = _overrides()
    return [t.describe() | {"enabled": is_enabled(t, overrides)} for t in all_tools()]


def set_enabled(name: str, enabled: bool) -> None:
    from app.catalog import get_catalog

    if not any(t.name == name for t in all_tools()):
        raise ValueError(f"No tool named {name!r}")
    overrides = _overrides()
    overrides[name] = enabled
    get_catalog().set_setting(_OVERRIDES_KEY, overrides)


__all__ = [
    "BUILTIN",
    "EXTERNAL_SOURCES",
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "all_tools",
    "describe_all",
    "enabled_tools",
    "is_enabled",
    "set_enabled",
]
