import logging
from pathlib import Path
from typing import Optional

from langchain_chroma import Chroma

from app.config import get_settings
from app.storage.manager import StorageFactory
from app.storage.main import Store

logger = logging.getLogger(__name__)


@StorageFactory.register_store("chromadb")
class ChromaStore(Store):
    """
    ChromaDB-backed vector store, one collection per namespace/workspace.

    The collection is created with an explicit cosine space so that
    ``similarity_search_with_relevance_scores`` returns comparable 0-1 scores.
    Chroma's default metric is L2, whose normalisation is not comparable with
    the BM25 and cross-encoder scores shown alongside it in the Retrieval Lab.
    """

    COLLECTION_CONFIG = {"hnsw": {"space": "cosine"}}

    @staticmethod
    def _relevance(distance: float) -> float:
        """
        Map cosine distance to a relevance score.

        LangChain's default for cosine is ``1 - distance``, which goes negative
        for any pair more than 90 degrees apart and triggers a runtime warning.
        Cosine distance is bounded to [0, 2], so halving it gives a monotonic
        score that is always within [0, 1] without clamping.
        """
        return 1.0 - (distance / 2.0)

    def __init__(
        self,
        namespace: str,
        persist_dir: Optional[str] = None,
        embedding_function=None,
    ):
        settings = get_settings()
        self.namespace = namespace
        self.persist_dir = str(persist_dir or settings.persistent_storage)
        Path(self.persist_dir).mkdir(parents=True, exist_ok=True)

        if embedding_function is None:
            # Imported lazily: app.runtime imports storage, so a module-level
            # import here would be circular.
            from app.runtime.resources import get_embedding

            embedding_function = get_embedding()

        logger.info(
            "Opening Chroma collection %r at %s", namespace, self.persist_dir
        )
        self.vector_store = Chroma(
            collection_name=namespace,
            persist_directory=self.persist_dir,
            embedding_function=embedding_function,
            collection_configuration=self.COLLECTION_CONFIG,
            relevance_score_fn=self._relevance,
        )

    def get_vector_store(self) -> Chroma:
        return self.vector_store

    def count(self) -> int:
        try:
            return self.vector_store._collection.count()
        except Exception:
            logger.exception("Failed to count collection %r", self.namespace)
            return 0

    def reset(self) -> None:
        """Drop every document in the collection, keeping the collection itself."""
        logger.info("Resetting Chroma collection %r", self.namespace)
        self.vector_store.reset_collection()

    def drop(self) -> None:
        """Delete the collection outright."""
        logger.info("Deleting Chroma collection %r", self.namespace)
        try:
            self.vector_store.delete_collection()
        except Exception:
            logger.exception("Failed to delete collection %r", self.namespace)
