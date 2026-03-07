from abc import ABC, abstractmethod

class LanguageModel(ABC):
    def __init__(self, **kwargs):
        self.params = kwargs
    
    @abstractmethod
    def generate_response(self, prompt: str) -> str:
        pass
