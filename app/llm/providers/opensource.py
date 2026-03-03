from typing import Optional
from langchain_ollama import OllamaLLM

class OpenSourceModel:
    def __init__(
            self, 
            model_name: str = "llama3.1:8b", 
            temperature: float = 0.7
        ):
        self.model_name = model_name
        self.temperature = temperature

        self.llm = OllamaLLM(
            model=model_name, 
            temperature=temperature
        )

    def generate_response(self, prompt: str) -> str:
        responce = self.llm.invoke(prompt)
        return responce.content
    

