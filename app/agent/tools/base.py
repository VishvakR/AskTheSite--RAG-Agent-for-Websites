"""
Tool framework.

A tool is a name, a description, an argument schema and a handler. Built-in
tools declare their arguments as a pydantic model (which doubles as the JSON
schema the model sees and as input validation); MCP tools bring a raw JSON
schema instead. Both run through :meth:`Tool.run`, which validates, applies
the timeout, and turns every failure into an error *result* the model can read
and react to -- a tool never raises into the loop.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type, Union

from pydantic import BaseModel, ValidationError

from app.llm.types import ToolSpec

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    # Structured payload for the UI (never sent to the model).
    data: Any = None
    elapsed_ms: int = 0

    @classmethod
    def error(cls, message: str) -> "ToolResult":
        return cls(content=f"Error: {message}", is_error=True)


@dataclass
class ToolContext:
    """What a tool may touch during one turn."""

    session: Any
    workspaces: List[Any]
    ledger: Any
    engine: str = "auto"
    top_k: int = 5
    settings: Any = None
    extras: Dict[str, Any] = field(default_factory=dict)

    def workspace(self, ref: Optional[str]):
        """Resolve a workspace by id or (case-insensitive) name."""
        if not ref:
            return None
        ref_l = ref.lower()
        for ws in self.workspaces:
            if ws.id == ref or ws.name.lower() == ref_l:
                return ws
        return None


Handler = Callable[[ToolContext, Any], Union[ToolResult, Awaitable[ToolResult]]]


@dataclass
class Tool:
    name: str
    description: str
    handler: Handler
    args_model: Optional[Type[BaseModel]] = None
    input_schema: Optional[Dict[str, Any]] = None
    source: str = "builtin"
    enabled_by_default: bool = True
    # Shown in settings so people know what a tool can do before enabling it.
    risk: str = "read"  # read | network | write

    def schema(self) -> Dict[str, Any]:
        if self.input_schema is not None:
            return self.input_schema
        if self.args_model is None:
            return {"type": "object", "properties": {}}
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        return schema

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, input_schema=self.schema())

    def describe(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "risk": self.risk,
            "enabled_by_default": self.enabled_by_default,
            "input_schema": self.schema(),
        }

    async def run(self, ctx: ToolContext, arguments: Dict[str, Any], timeout: float) -> ToolResult:
        started = time.perf_counter()
        try:
            if "__invalid_json__" in arguments:
                raise ValueError("arguments were not valid JSON; send a JSON object")
            args: Any = arguments
            if self.args_model is not None:
                args = self.args_model.model_validate(arguments)

            if inspect.iscoroutinefunction(self.handler):
                pending = self.handler(ctx, args)
            else:
                # Retrieval and file IO block; keep them off the event loop.
                pending = asyncio.to_thread(self.handler, ctx, args)
            result = await asyncio.wait_for(pending, timeout=timeout)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}"
                for e in exc.errors()
            )
            result = ToolResult.error(f"invalid arguments ({problems})")
        except asyncio.TimeoutError:
            result = ToolResult.error(f"{self.name} timed out after {timeout:.0f}s")
        except Exception as exc:
            logger.exception("Tool %s failed", self.name)
            result = ToolResult.error(f"{exc.__class__.__name__}: {exc}")
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return result


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def add(self, tool: Tool) -> Tool:
        self._tools[tool.name] = tool
        return tool

    def remove(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all(self) -> List[Tool]:
        return list(self._tools.values())

    def tool(
        self,
        name: str,
        description: str,
        args: Optional[Type[BaseModel]] = None,
        **options: Any,
    ):
        """Decorator: register a function as a tool."""

        def wrap(fn: Handler) -> Handler:
            self.add(Tool(name=name, description=description, handler=fn, args_model=args, **options))
            return fn

        return wrap


#: Tools that ship with AskTheSite.
BUILTIN = ToolRegistry()
