import os
import certifi
from pymongo import MongoClient

from langchain_mongodb import MongoDBAtlasVectorSearch
from app.embeddings.embedding import Embedding
from app.storage.main import Store
from app.storage.manager import StorageFactory
import logging


from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

uri = os.getenv('MONGODB_URI')

@StorageFactory.register_store("mongodb")
class MongoStorage(Store):
    def __init__(
            self,
            namespace: str,
            uri: str = uri,
        ):
        self.DB_NAME = 'AskTheSite'
        self.COLLECTION_NAME = namespace
        self.ATLAS_VECTOR_SEARCH_INDEX_NAME = "vector_indexes"

        logger.info(f"Initializing MongoStorage with namespace: {namespace} and uri: {uri}")
        self.client = MongoClient(uri,
                                  tls=True,
                                  tlsCAFile=certifi.where()
                                )
        
        self.database = self.client[self.DB_NAME]
        
        if self.COLLECTION_NAME not in self.client[self.DB_NAME].list_collection_names():

            self.vector_store = MongoDBAtlasVectorSearch(
                collection=self.database[self.COLLECTION_NAME],
                embedding=Embedding().get_embedding_function(),
                index_name=self.ATLAS_VECTOR_SEARCH_INDEX_NAME,
                relevance_score_fn="cosine",
            )

            self.vector_store.create_vector_search_index(dimensions=384)
            
        else:
            self.collection = self.database[self.COLLECTION_NAME]

            self.vector_store = MongoDBAtlasVectorSearch(
                collection=self.collection,
                embedding=Embedding().get_embedding_function(),
                index_name=self.ATLAS_VECTOR_SEARCH_INDEX_NAME,
            )
        logger.info(f"MongoStorage initialized successfully with collection: {self.COLLECTION_NAME}")

    def get_vector_store(self):
        return self.vector_store

    def close(self):
        """Close the MongoDB client connection."""
        if self.client:
            self.client.close()
            logger.info(f"MongoStorage connection closed for collection: {self.COLLECTION_NAME}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False