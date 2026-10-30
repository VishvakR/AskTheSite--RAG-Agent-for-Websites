import logging
from typing import Iterator, Optional

from langchain_anthropic import ChatAnthropic

from app.llm.main import LanguageModel
from app.llm.manager import LanguageModelFactory

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"


@LanguageModelFactory.register("anthropic")
class AnthropicModel(LanguageModel):
    """
    Claude via ``langchain-anthropic``.

    LangChain-consistent with the rest of the LLM layer (``ChatAnthropic``
    wraps the official Anthropic SDK), so it slots into the same factory and
    streaming contract as the Ollama and OpenAI providers.
    """

    provider = "anthropic"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
        max_tokens: int = 16000,
    ):
        from app.config import get_settings

        settings = get_settings()
        self.model_name = model_name or DEFAULT_MODEL
        self.temperature = settings.llm_temperature if temperature is None else temperature
        self.api_key = api_key or settings.anthropic_api_key
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Add it to .env or choose another provider."
            )

        self.llm = ChatAnthropic(
            model=self.model_name,
            temperature=self.temperature,
            api_key=self.api_key,
            max_tokens=max_tokens,
        )

    def generate_response(self, prompt: str) -> str:
        response = self.llm.invoke(prompt)
        content = response.content
        if isinstance(content, list):
            # Content can come back as a list of blocks.
            return "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )
        return content

    def stream_response(self, prompt: str) -> Iterator[str]:
        for chunk in self.llm.stream(prompt):
            content = getattr(chunk, "content", "")
            if isinstance(content, list):
                for block in content:
                    text = block.get("text", "") if isinstance(block, dict) else str(block)
                    if text:
                        yield text
            elif content:
                yield content
