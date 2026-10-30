"""Provider registry and availability probing."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Type

from .main import LanguageModel

logger = logging.getLogger(__name__)


class LanguageModelFactory:
    _registry: Dict[str, Type[LanguageModel]] = {}

    @classmethod
    def register(cls, model_type: str):
        def inner_wrapper(wrapped_class: Type[LanguageModel]):
            cls._registry[model_type.lower()] = wrapped_class
            return wrapped_class

        return inner_wrapper

    @classmethod
    def registered(cls) -> List[str]:
        return sorted(cls._registry)


class LLMManager:
    @staticmethod
    def create(model_type: str, **kwargs) -> LanguageModel:
        model_cls = LanguageModelFactory._registry.get(model_type.lower())
        if not model_cls:
            raise ValueError(
                f"Model type {model_type!r} not registered. "
                f"Available: {LanguageModelFactory.registered()}"
            )
        return model_cls(**kwargs)

    @staticmethod
    def availability() -> List[Dict[str, Any]]:
        """
        Report which providers are actually usable right now.

        The UI uses this to avoid offering a provider whose key is missing or
        whose Ollama daemon is not running -- previously the only way to find
        out was a 500 at query time.
        """
        from app.config import get_settings

        settings = get_settings()
        out: List[Dict[str, Any]] = []

        # Ollama: reachable, and which models are actually pulled?
        models: List[str] = []
        reason = None
        try:
            import requests

            resp = requests.get(f"{settings.ollama_base_url}/api/tags", timeout=2)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            available = bool(models)
            if not available:
                reason = "Ollama is running but no models are pulled (try: ollama pull llama3.1:8b)"
        except Exception as exc:
            available = False
            reason = f"Ollama unreachable at {settings.ollama_base_url} ({exc.__class__.__name__})"

        out.append({
            "provider": "opensource",
            "label": "Ollama (local)",
            "available": available,
            "reason": reason,
            "models": models,
            "default_model": settings.llm_model,
            "requires_key": False,
        })

        for provider, label, key, defaults in (
            ("anthropic", "Anthropic Claude", settings.anthropic_api_key,
             ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]),
            ("openai", "OpenAI", settings.openai_api_key,
             ["gpt-4o-mini", "gpt-4o"]),
        ):
            out.append({
                "provider": provider,
                "label": label,
                "available": bool(key),
                "reason": None if key else f"{provider.upper()}_API_KEY is not set",
                "models": defaults,
                "default_model": defaults[0],
                "requires_key": True,
            })

        return out
