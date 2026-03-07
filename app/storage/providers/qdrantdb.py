import os
from qdrant_client import QdrantClient
from langchain_qdrant import QdrantVectorStore
from dotenv import load_dotenv

from app.embeddings.embedding import Embedding

load_dotenv()

QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")


class QdrantStorage:
    def __init__(
        self,
        namespace: str,
        url: str = QDRANT_URL,
        api_key: str = QDRANT_API_KEY
    ):

        self.COLLECTION_NAME = namespace
        self.VECTOR_SIZE = 384

        # Qdrant client
        self.client = QdrantClient(
            url=url,
            api_key=api_key
        )

        # Check if collection exists
        collections = [c.name for c in self.client.get_collections().collections]

        if self.COLLECTION_NAME not in collections:

            self.client.create_collection(
                collection_name=self.COLLECTION_NAME,
                vectors_config={
                    "size": self.VECTOR_SIZE,
                    "distance": "Cosine"
                }
            )

        # Vector store
        self.vector_store = QdrantVectorStore(
            client=self.client,
            collection_name=self.COLLECTION_NAME,
            embedding=Embedding().get_embedding_function()
        )

    def get_vector_store(self):
        return self.vector_store