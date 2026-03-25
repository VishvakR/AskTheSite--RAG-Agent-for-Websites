import os
import logging
from typing import Optional, List

from langchain_core.documents import Document

from app.llm.main import LanguageModel
from app.llm.manager import LLMManager
from app.storage.manager import StoreManager
from app.index.main import IndexBase
from app.index.manager import IndexManager
from app.ingestion.parsing import Documents

logger = logging.getLogger(__name__)


class RAGAgent:

    def __init__(
        self,
        llm: LanguageModel,
        storage: StoreManager,
        index: IndexBase,
        document: Optional[Documents] = None,
        phoenix_api_key: Optional[str] = None,
    ):
        if llm is None:
            raise TypeError("Missing required argument 'llm'")
        if storage is None:
            raise TypeError("Missing required argument 'storage'")
        if index is None:
            raise TypeError("Missing required argument 'index'")

        self.llm = llm
        self.storage_manager = storage
        self.index_manager = index
        self.document_handler = document

        # Optional: enable Arize Phoenix tracing via OpenTelemetry.
        # Set the OTLP auth header so traces are streamed to llamatrace.com.
        if phoenix_api_key:
            os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"api_key={phoenix_api_key}"
            logger.info("Arize Phoenix tracing enabled.")


    def create_index(self) -> None:
        """Ingest documents and build (or refresh) the vector index."""
        self.index_manager.create_index()

 
    def get_relevant_nodes(self, prompt: str, top_k: int = 5) -> List[Document]:
        """
        Retrieve the most relevant document chunks for *prompt*.
        """
        return self.index_manager.query(prompt)

    def get_documents(self) -> List[Document]:
        """
        Load and return the raw source documents (before chunking/indexing).
        """
        if self.document_handler is None:
            raise ValueError(
                "No document handler set. Pass a Documents instance when "
                "constructing RAGAgent."
            )
        return self.document_handler.load_documents()

 
    def run(self, prompt: str) -> str:
        """
        Full RAG pipeline: retrieve relevant chunks then generate a response.

        Args:
            prompt: The user query.

        Returns:
            A generated answer string from the LLM.
        """
        docs = self.get_relevant_nodes(prompt)

        context = "\n\n".join(doc.page_content for doc in docs)

        augmented_prompt = (
            f"Use the following context to answer the question.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {prompt}"
        )

        return self.llm.generate_response(augmented_prompt)