"""
Citation markers that stay stable across a whole session.

An agent may search five times in one answer, and a session may span many
answers. If every search numbered its results from ``[1]``, the model would
see several different "[1]"s in its context and cite the wrong one. The
ledger hands out one marker per distinct chunk for the life of the session:
a chunk found again keeps its number, and new chunks continue the sequence.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def _key(c: Dict[str, Any]) -> str:
    if c.get("chunk_id"):
        return f"id:{c['chunk_id']}"
    return f"{c.get('source_url', '')}#{c.get('chunk_index', 0)}:{c.get('heading', '')}"


class CitationLedger:
    def __init__(self, prior: Optional[Iterable[Dict[str, Any]]] = None) -> None:
        self._by_key: Dict[str, Dict[str, Any]] = {}
        self._next = 1
        # Markers touched during the current turn, in first-touched order.
        self._touched: List[int] = []
        self._by_marker: Dict[int, Dict[str, Any]] = {}
        for c in prior or []:
            if "marker" in c:
                self._by_key.setdefault(_key(c), c)
                self._by_marker.setdefault(c["marker"], c)
                self._next = max(self._next, int(c["marker"]) + 1)

    def add(self, citation: Dict[str, Any]) -> Dict[str, Any]:
        """Register a chunk; return it with its (possibly existing) marker."""
        key = _key(citation)
        existing = self._by_key.get(key)
        if existing is None:
            existing = dict(citation, marker=self._next)
            self._next += 1
            self._by_key[key] = existing
            self._by_marker[existing["marker"]] = existing
        else:
            # Keep the freshest score/snippet but never renumber.
            existing.update({k: v for k, v in citation.items() if k != "marker"})
        if existing["marker"] not in self._touched:
            self._touched.append(existing["marker"])
        return existing

    def get(self, marker: int) -> Optional[Dict[str, Any]]:
        return self._by_marker.get(marker)

    def turn_citations(self) -> List[Dict[str, Any]]:
        """Everything retrieved this turn, in the order it was first seen."""
        return [self._by_marker[m] for m in self._touched]

    def __len__(self) -> int:
        return len(self._touched)
