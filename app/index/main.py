from abc import ABC, abstractmethod

class IndexBase(ABC):
    @abstractmethod
    def create_index(self, documents):
        pass

    