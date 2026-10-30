import logging
from typing import Iterator, Optional

from langchain_openai import ChatOpenAI

from app.llm.main import LanguageModel
from app.llm.manager import LanguageModelFactory

logger = logging.getLogger(__name__)


@LanguageModelFactory.register("openai")
class OpenAIModel(LanguageModel):
    """LangChain-backed OpenAI chat model."""

    provider = "openai"

    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
    ):
        from app.config import get_settings

        settings = get_settings()
        self.model_name = model_name
        self.temperature = settings.llm_temperature if temperature is None else temperature
        # Nothing ever passed this before, so the key was only ever picked up
        # from the ambient environment.
        self.api_key = api_key or settings.openai_api_key
        if not self.api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set. Add it to .env or choose another provider."
            )

        self.llm = ChatOpenAI(
            model=model_name,
            temperature=self.temperature,
            api_key=self.api_key,
        )

    def generate_response(self, prompt: str) -> str:
        return self.llm.invoke(prompt).content

    def stream_response(self, prompt: str) -> Iterator[str]:
        for chunk in self.llm.stream(prompt):
            text = getattr(chunk, "content", "")
            if text:
                yield text
