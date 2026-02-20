import os
from langchain_chroma import Chroma

from dotenv import load_dotenv
load_dotenv()

PERSISTENT_STORAGE = os.getenv('PERSISTENT_STORAGE')

class ChromaStore:
    def __init__(
            self,
            namespace: str,
            persist_dir: str = PERSISTENT_STORAGE,
        ):

        self.vector_store = Chroma(
            collection_name=namespace,
            persist_directory=persist_dir
        )

    def get_vector_store(self):
        return self.vector_store
