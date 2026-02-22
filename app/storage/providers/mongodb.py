import os
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

from langchain_mongodb import MongoDBAtlasVectorSearch

from dotenv import load_dotenv
load_dotenv()

uri = os.getenv('MONGODB_URI');

class MongoStorage:
    def __init__(
            self,
            namespace: str,
            uri: str = uri,
        ):
        
        self.client = MongoClient(uri)
        self.database = self.client['askthesitee']
        self.collection = self.database[namespace]

        self.vector_store = MongoDBAtlasVectorSearch(
            collection=self.collection,
            index_name='vector_search'
        )