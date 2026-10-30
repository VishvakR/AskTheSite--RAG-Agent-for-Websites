"""
Scored retrieval across the three strategies.

The retrievers used to return bare ``Document`` lists with no scores, which is
why the UI could never show *why* a chunk was retrieved.  Each strategy here
returns a comparable 0-1 score so the three can be shown side by side:

* ``auto``   -- Chroma cosine relevance (the collection is created with an
  explicit cosine space; Chroma's default is L2, whose normalisation is not
  comparable with the other two).
* ``bm25``   -- ``BM25Retriever`` exposes no scores, but the underlying
  ``rank_bm25`` vectorizer does; scores are normalised by the batch maximum.
* ``rerank`` -- the cross-encoder returns raw logits, mapped through a sigmoid.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from app.index.providers.type import QueryEngineType
from app.runtime.resources import get_bm25, get_cross_encoder, get_store

logger = logging.getLogger(__name__)

SNIPPET_CHARS = 320


@dataclass
class ScoredChunk:
    rank: int
    score: float
    content: str
    chunk_id: Optional[str] = None
    source_url: str = ""
    page_title: str = ""
    heading: str = ""
    page_id: str = ""
    chunk_index: int = 0

    @property
    def snippet(self) -> str:
        text = " ".join(self.content.split())
        return text[:SNIPPET_CHARS] + ("…" if len(text) > SNIPPET_CHARS else "")

    def to_dict(self, include_content: bool = False) -> Dict[str, Any]:
        d = asdict(self)
        d["snippet"] = self.snippet
        if not include_content:
            d.pop("content", None)
        return d

    @classmethod
    def from_document(cls, doc: Document, rank: int, score: float) -> "ScoredChunk":
        meta = doc.metadata or {}
        return cls(
            rank=rank,
            score=round(float(score), 4),
            content=doc.page_content,
            chunk_id=getattr(doc, "id", None),
            source_url=str(meta.get("source_url", "")),
            page_title=str(meta.get("page_title", "")),
            heading=str(meta.get("heading", "")),
            page_id=str(meta.get("page_id", "")),
            chunk_index=int(meta.get("chunk_index", 0) or 0),
        )


@dataclass
class RetrievalResult:
    engine: str
    results: List[ScoredChunk] = field(default_factory=list)
    elapsed_ms: int = 0
    error: Optional[str] = None

    def to_dict(self, include_content: bool = False) -> Dict[str, Any]:
        return {
            "engine": self.engine,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
            "results": [r.to_dict(include_content) for r in self.results],
        }


def _sigmoid(x: float) -> float:
    # Guard against overflow on large-magnitude logits.
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-min(x, 60.0)))
    e = math.exp(max(x, -60.0))
    return e / (1.0 + e)


def _dedupe_key(doc: Document) -> tuple:
    meta = doc.metadata or {}
    return (meta.get("page_id", ""), meta.get("chunk_index", -1), doc.page_content[:80])


# ── strategies ────────────────────────────────────────────────────────────


def _retrieve_auto(collection_name: str, query: str, top_k: int) -> List[ScoredChunk]:
    store = get_store(collection_name)
    pairs = store.get_vector_store().similarity_search_with_relevance_scores(
        query, k=top_k
    )
    return [
        ScoredChunk.from_document(doc, rank=i + 1, score=max(0.0, min(1.0, score)))
        for i, (doc, score) in enumerate(pairs)
    ]


def _retrieve_bm25(
    collection_name: str, index_version: int, query: str, top_k: int
) -> List[ScoredChunk]:
    retriever = get_bm25(collection_name, index_version, top_k=top_k)
    tokens = retriever.preprocess_func(query)
    raw = retriever.vectorizer.get_scores(tokens)

    ranked = sorted(range(len(raw)), key=lambda i: raw[i], reverse=True)[:top_k]
    peak = max((raw[i] for i in ranked), default=0.0)

    out: List[ScoredChunk] = []
    for rank, idx in enumerate(ranked, start=1):
        if raw[idx] <= 0:
            continue
        normalized = float(raw[idx]) / peak if peak > 0 else 0.0
        out.append(ScoredChunk.from_document(retriever.docs[idx], rank, normalized))
    return out


def _retrieve_rerank(
    collection_name: str,
    index_version: int,
    query: str,
    top_k: int,
    candidate_multiplier: int = 3,
) -> List[ScoredChunk]:
    """Union the vector and BM25 candidate pools, then rescore with the cross-encoder."""
    candidate_k = max(top_k * candidate_multiplier, 10)

    store = get_store(collection_name)
    vector_docs = store.get_vector_store().similarity_search(query, k=candidate_k)

    try:
        bm25 = get_bm25(collection_name, index_version, top_k=candidate_k)
        keyword_docs = bm25.invoke(query)
    except ValueError:
        keyword_docs = []

    candidates: List[Document] = []
    seen = set()
    for doc in [*vector_docs, *keyword_docs]:
        key = _dedupe_key(doc)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(doc)

    if not candidates:
        return []

    encoder = get_cross_encoder()
    scores = encoder.score([(query, d.page_content) for d in candidates])

    order = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [
        ScoredChunk.from_document(candidates[i], rank=r, score=_sigmoid(float(scores[i])))
        for r, i in enumerate(order, start=1)
    ]


# ── public API ────────────────────────────────────────────────────────────

VALID_ENGINES = {
    QueryEngineType.AUTO.value,
    QueryEngineType.BM25.value,
    QueryEngineType.RERANK.value,
}


def retrieve(
    collection_name: str,
    index_version: int,
    query: str,
    engine: str = QueryEngineType.AUTO.value,
    top_k: int = 5,
) -> RetrievalResult:
    """Run one strategy and return scored, ranked chunks."""
    if engine not in VALID_ENGINES:
        raise ValueError(
            f"Unsupported query engine {engine!r}. Valid options: {sorted(VALID_ENGINES)}"
        )

    started = time.perf_counter()
    try:
        if engine == QueryEngineType.AUTO.value:
            results = _retrieve_auto(collection_name, query, top_k)
        elif engine == QueryEngineType.BM25.value:
            results = _retrieve_bm25(collection_name, index_version, query, top_k)
        else:
            results = _retrieve_rerank(collection_name, index_version, query, top_k)
        error = None
    except ValueError as exc:
        # Empty collection is an expected, reportable state -- not a crash.
        logger.warning("Retrieval (%s) failed: %s", engine, exc)
        results, error = [], str(exc)

    return RetrievalResult(
        engine=engine,
        results=results,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        error=error,
    )


def compare(
    collection_name: str, index_version: int, query: str, top_k: int = 5
) -> Dict[str, Any]:
    """
    Run all three strategies over the same question.

    This is the Retrieval Lab: it makes the retrieval step inspectable instead
    of a black box, and surfaces which chunks the strategies agree on.
    """
    strategies = {
        engine: retrieve(collection_name, index_version, query, engine, top_k)
        for engine in (
            QueryEngineType.AUTO.value,
            QueryEngineType.BM25.value,
            QueryEngineType.RERANK.value,
        )
    }

    def key(chunk: ScoredChunk) -> str:
        return f"{chunk.page_id}:{chunk.chunk_index}"

    sets = {name: {key(c) for c in res.results} for name, res in strategies.items()}
    non_empty = [s for s in sets.values() if s]
    shared = set.intersection(*non_empty) if len(non_empty) > 1 else set()
    union = set.union(*sets.values()) if any(sets.values()) else set()

    # Pairwise overlap is the informative signal: the intersection of all three
    # strategies is usually empty even when two of them agree closely, so a
    # single "agreement" number on its own is misleading.
    pairwise = {}
    names = list(sets)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            both, either = sets[a] & sets[b], sets[a] | sets[b]
            pairwise[f"{a}|{b}"] = {
                "shared_count": len(both),
                "jaccard": round(len(both) / len(either), 3) if either else 0.0,
                "shared": sorted(both),
            }

    return {
        "query": query,
        "top_k": top_k,
        "strategies": {n: r.to_dict() for n, r in strategies.items()},
        "overlap": {
            "shared": sorted(shared),
            "shared_count": len(shared),
            "union_count": len(union),
            "agreement": round(len(shared) / len(union), 3) if union else 0.0,
            "pairwise": pairwise,
            "per_strategy": {n: sorted(s) for n, s in sets.items()},
        },
    }
