"""
Process-wide cache for the expensive, reusable pieces of the RAG pipeline.

This replaces the old ``_agent`` singleton in ``server.py``.  That singleton
cached the *whole* agent, so after the first request every per-request
parameter (namespace, engine, top_k, model) was silently ignored -- and because
FastAPI runs sync ``def`` routes in a threadpool, it was also a data race.

The fix is to cache only what is genuinely expensive to build:

* the embedding model      -- was re-instantiated in every store constructor
* the cross-encoder        -- was reloaded on *every* rerank query
* the Chroma handle        -- one per workspace
* the BM25 index           -- was rebuilt from the whole collection per query

Everything else (``RAGAgent``, retrievers) is cheap once these are warm, so it
is constructed per request with the caller's real parameters.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_lock = threading.RLock()

_embedding: Any = None
_cross_encoders: Dict[str, Any] = {}
_stores: Dict[str, Any] = {}
_bm25: Dict[str, Tuple[int, Any]] = {}   # workspace_id -> (index_version, retriever)


def get_embedding():
    """The shared sentence-transformer embedding function (loaded once)."""
    global _embedding
    with _lock:
        if _embedding is None:
            from app.config import get_settings
            from langchain_huggingface import HuggingFaceEmbeddings

            settings = get_settings()
            logger.info("Loading embedding model %s", settings.embedding_model)
            _embedding = HuggingFaceEmbeddings(
                model_name=settings.embedding_model,
                cache_folder=str(settings.embedding_cache),
            )
        return _embedding


def get_cross_encoder(model_name: Optional[str] = None):
    """The shared HuggingFace cross-encoder used for reranking."""
    from app.config import get_settings

    model_name = model_name or get_settings().rerank_model
    with _lock:
        if model_name not in _cross_encoders:
            from langchain_community.cross_encoders import HuggingFaceCrossEncoder

            logger.info("Loading cross-encoder %s", model_name)
            _cross_encoders[model_name] = HuggingFaceCrossEncoder(model_name=model_name)
        return _cross_encoders[model_name]


def get_store(collection_name: str):
    """Cached :class:`ChromaStore` for one workspace collection."""
    with _lock:
        if collection_name not in _stores:
            from app.storage.providers.chroma import ChromaStore

            _stores[collection_name] = ChromaStore(namespace=collection_name)
        return _stores[collection_name]


def get_bm25(collection_name: str, index_version: int, top_k: int = 5):
    """
    Cached BM25 retriever, invalidated when ``index_version`` changes.

    Building it means pulling the entire collection out of Chroma, so doing it
    per query (as the old code did) is O(collection) on every request.
    """
    with _lock:
        cached = _bm25.get(collection_name)
        if cached and cached[0] == index_version:
            retriever = cached[1]
            retriever.k = top_k
            return retriever

        from langchain_community.retrievers import BM25Retriever

        store = get_store(collection_name)
        result = store.get_vector_store().get()
        texts = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        if not texts:
            raise ValueError(
                f"Collection {collection_name!r} is empty -- ingest documents "
                "before running a BM25 or rerank query."
            )

        logger.info(
            "Building BM25 index for %s (%d chunks, version %d)",
            collection_name, len(texts), index_version,
        )
        retriever = BM25Retriever.from_texts(texts=texts, metadatas=metadatas)
        retriever.k = top_k
        _bm25[collection_name] = (index_version, retriever)
        return retriever


def invalidate_workspace(collection_name: str) -> None:
    """Drop cached per-workspace resources after an ingest or delete."""
    with _lock:
        _bm25.pop(collection_name, None)
        _stores.pop(collection_name, None)
    logger.debug("Invalidated cached resources for %s", collection_name)


def reset_all() -> None:
    """Test hook -- clears every cached resource."""
    global _embedding
    with _lock:
        _embedding = None
        _cross_encoders.clear()
        _stores.clear()
        _bm25.clear()
