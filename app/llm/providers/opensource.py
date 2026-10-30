import logging
from typing import Iterator, Optional

from langchain_ollama import OllamaLLM

from app.llm.main import LanguageModel
from app.llm.manager import LanguageModelFactory

logger = logging.getLogger(__name__)


@LanguageModelFactory.register("opensource")
class OpenSourceModel(LanguageModel):
    """Ollama-backed local model. The zero-key default -- runs fully offline."""

    provider = "opensource"

    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        base_url: Optional[str] = None,
    ):
        from app.config import get_settings

        settings = get_settings()
        self.model_name = model_name or settings.llm_model
        self.temperature = settings.llm_temperature if temperature is None else temperature
        # Previously hardcoded to Ollama's localhost default, which breaks in Docker.
        self.base_url = base_url or settings.ollama_base_url

        self.llm = OllamaLLM(
            model=self.model_name,
            temperature=self.temperature,
            base_url=self.base_url,
        )

    def generate_response(self, prompt: str) -> str:
        return self.llm.invoke(prompt)

    def stream_response(self, prompt: str) -> Iterator[str]:
        for chunk in self.llm.stream(prompt):
            if chunk:
                yield chunk
