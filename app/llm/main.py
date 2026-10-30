"""Language-model abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator


class LanguageModel(ABC):
    """
    Base class for every LLM provider.

    ``stream_response`` has a working default that simply yields the whole
    answer, so providers that predate streaming keep working untouched;
    providers override it to stream token by token.
    """

    #: Human-readable provider key, set by subclasses.
    provider: str = "unknown"
    model_name: str = ""

    @abstractmethod
    def generate_response(self, prompt: str) -> str:
        """Return the complete answer for *prompt*."""

    def stream_response(self, prompt: str) -> Iterator[str]:
        """Yield the answer in pieces. Default: one piece."""
        yield self.generate_response(prompt)

    def describe(self) -> dict:
        return {"provider": self.provider, "model": self.model_name}
