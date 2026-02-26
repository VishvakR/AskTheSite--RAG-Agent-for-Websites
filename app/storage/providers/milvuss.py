import os
from langchain_milvus import Milvus
from dotenv import load_dotenv

load_dotenv()

class MilvusStore:
    def __init__(
            self,
            namespace: str,
            uri: str = os.getenv('PERSISTENT_STORAGE'),
        ):
        self.namespace = namespace
        self.uri = uri

        self.vector_store = Milvus(
            embedding_function=embedding_function,
            connection_args={"uri": uri},
            collection_name=namespace,
        )

    def get_vector_store(self):
        return self.vector_store
    
