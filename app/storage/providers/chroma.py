import os
from langchain_chroma import Chroma

from dotenv import load_dotenv
load_dotenv()


class ChromaStore:
    def __init__(
            self,
            namespace: str,
            persist_dir: str = os.getenv('PERSISTENT_STORAGE'),
        ):
        self.namespace = namespace
        self.persist_dir = persist_dir

        self.vector_store = Chroma(
            collection_name=namespace,
            persist_directory=persist_dir
        )


    def get_vector_store(self):
        return self.vector_store
    
