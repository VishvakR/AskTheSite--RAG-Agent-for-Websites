"""Retrieval across one or several workspaces, merged into one ranking."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Sequence, Tuple

from app.index.retrieval import ScoredChunk, retrieve

logger = logging.getLogger(__name__)


def search_workspaces(
    workspaces: Sequence[Any], query: str, engine: str, top_k: int
) -> Tuple[List[Tuple[Any, ScoredChunk]], List[str]]:
    """
    Run *engine* over every workspace and keep the best *top_k* overall.

    Scores are 0-1 within each strategy, so they are comparable across
    workspaces using the same strategy. Returns ``(hits, errors)`` where each
    hit pairs the chunk with the workspace it came from.
    """
    hits: List[Tuple[Any, ScoredChunk]] = []
    errors: List[str] = []
    for ws in workspaces:
        try:
            result = retrieve(ws.collection_name, ws.index_version, query, engine, top_k)
        except Exception as exc:
            logger.exception("Search failed in %s", ws.id)
            errors.append(f"{ws.name}: {exc}")
            continue
        if result.error:
            errors.append(f"{ws.name}: {result.error}")
        hits.extend((ws, chunk) for chunk in result.results)
    hits.sort(key=lambda pair: pair[1].score, reverse=True)
    return hits[:top_k], errors


def citation_for(ws: Any, chunk: ScoredChunk) -> Dict[str, Any]:
    payload = chunk.to_dict()
    payload["workspace_id"] = ws.id
    payload["workspace_name"] = ws.name
    return payload


def format_hit(marker: int, chunk: ScoredChunk, max_chars: int = 1500) -> str:
    label = chunk.page_title or chunk.source_url or "source"
    where = f"{label} — {chunk.heading}" if chunk.heading else label
    body = chunk.content if len(chunk.content) <= max_chars else chunk.content[:max_chars] + "…"
    return f"[{marker}] {where}\nURL: {chunk.source_url}\n\n{body}"
