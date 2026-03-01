import os
import certifi
from pymongo import MongoClient

from langchain_mongodb import MongoDBAtlasVectorSearch
from app.embeddings.embedding import Embedding

from dotenv import load_dotenv
load_dotenv()

uri = os.getenv('MONGODB_URI');

class MongoStorage:
    def __init__(
            self,
            namespace: str,
            uri: str = uri,
        ):
        self.DB_NAME = 'AskTheSite'
        self.COLLECTION_NAME = "askthesite"
        self.ATLAS_VECTOR_SEARCH_INDEX_NAME = "vector_indexes"


        self.client = MongoClient(uri,
                                  tls=True,
                                  tlsCAFile=certifi.where()
                                )
        
        self.database = self.client[self.DB_NAME]
        self.collection = self.database[self.COLLECTION_NAME]

        self.vector_store = MongoDBAtlasVectorSearch(
            collection=self.collection,
            embedding=Embedding().get_embedding_function(),
            index_name=self.ATLAS_VECTOR_SEARCH_INDEX_NAME,
        )