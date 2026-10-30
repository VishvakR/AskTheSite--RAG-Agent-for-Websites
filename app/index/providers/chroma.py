"""Chroma-backed index for one workspace collection."""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

from langchain_core.documents import Document

from app.index import IndexFactory
from app.index.retrieval import RetrievalResult, retrieve
from app.ingestion import Documents
from app.runtime.resources import get_store, invalidate_workspace

from .type import QueryEngineType

logger = logging.getLogger(__name__)

EMBED_BATCH = 64


@IndexFactory.registry("chroma")
class ChromaIndex:
    """
    Builds and queries the vector index for a single workspace.

    ``create_index`` resets the collection by default.  The old implementation
    only ever appended, so re-crawling a site duplicated every chunk with no
    way to clean up.
    """

    def __init__(
        self,
        collection_name: str,
        document: Optional[Documents] = None,
        index_version: int = 0,
        query_engine: str = QueryEngineType.AUTO.value,
        top_k: int = 5,
    ):
        self.collection_name = collection_name
        self.document_handler = document
        self.index_version = index_version
        self.query_engine = query_engine
        self.top_k = top_k

    @property
    def store(self):
        return get_store(self.collection_name)

    def count(self) -> int:
        return self.store.count()

    def create_index(
        self,
        reset: bool = True,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> int:
        """Chunk the workspace's pages and (re)build the vector index."""
        if self.document_handler is None:
            raise ValueError("Document handler is not provided")

        if on_progress:
            on_progress(0, 0, "Chunking pages")

        chunks: List[Document] = self.document_handler.create_nodes()
        if not chunks:
            logger.warning("No chunks produced for %s", self.collection_name)
            if reset:
                self.store.reset()
            invalidate_workspace(self.collection_name)
            return 0

        store = self.store
        if reset:
            logger.info("Resetting collection %s before ingest", self.collection_name)
            store.reset()

        vector_store = store.get_vector_store()
        total = len(chunks)
        for start in range(0, total, EMBED_BATCH):
            batch = chunks[start : start + EMBED_BATCH]
            vector_store.add_documents(batch)
            done = min(start + len(batch), total)
            if on_progress:
                on_progress(done, total, f"Embedded {done}/{total} chunks")

        invalidate_workspace(self.collection_name)
        logger.info("Indexed %d chunk(s) into %s", total, self.collection_name)
        return total

    def query(
        self,
        question: str,
        engine: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> RetrievalResult:
        """Scored retrieval for *question*."""
        return retrieve(
            self.collection_name,
            self.index_version,
            question,
            engine or self.query_engine,
            top_k or self.top_k,
        )
