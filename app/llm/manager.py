"""Provider registry and availability probing."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Type

from .main import LanguageModel
from .registry import ModelSpec, fallback_spec

logger = logging.getLogger(__name__)

# Display order in pickers; anything registered later is appended.
_ORDER = ["opensource", "anthropic", "openai", "openai_compatible"]


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
        known = [p for p in _ORDER if p in cls._registry]
        return known + sorted(p for p in cls._registry if p not in _ORDER)


class LLMManager:
    @staticmethod
    def provider_class(model_type: str) -> Type[LanguageModel]:
        model_cls = LanguageModelFactory._registry.get(model_type.lower())
        if not model_cls:
            raise ValueError(
                f"Model type {model_type!r} not registered. "
                f"Available: {LanguageModelFactory.registered()}"
            )
        return model_cls

    @staticmethod
    def create(model_type: str, **kwargs) -> LanguageModel:
        return LLMManager.provider_class(model_type)(**kwargs)

    @staticmethod
    def spec(provider: str, model: str) -> ModelSpec:
        """Capabilities of one model, falling back to provider defaults."""
        from app.config import get_settings

        cls = LanguageModelFactory._registry.get(provider.lower())
        spec_for = getattr(cls, "spec_for", None)
        if spec_for is None:
            return fallback_spec(provider, model)
        try:
            return spec_for(model, get_settings())
        except Exception:
            logger.debug("spec_for(%s, %s) failed", provider, model, exc_info=True)
            return fallback_spec(provider, model)

    @staticmethod
    def availability() -> List[Dict[str, Any]]:
        """
        Report which providers are usable right now, and what they offer.

        The UI uses this to avoid offering a provider whose key is missing or
        whose Ollama daemon is not running -- previously the only way to find
        out was a 500 at query time. Each provider answers for itself through
        its ``status`` / ``models`` classmethods, so a new provider shows up
        here just by registering.
        """
        from app.config import get_settings

        settings = get_settings()
        out: List[Dict[str, Any]] = []

        for name in LanguageModelFactory.registered():
            cls = LanguageModelFactory._registry[name]
            status = getattr(cls, "status", None)
            models = getattr(cls, "models", None)
            try:
                available, reason = status(settings) if status else (True, None)
            except Exception as exc:
                available, reason = False, f"{exc.__class__.__name__}: {exc}"
            try:
                specs: List[ModelSpec] = list(models(settings)) if models else []
            except Exception:
                logger.debug("Listing models for %s failed", name, exc_info=True)
                specs = []

            default: Optional[str] = None
            if hasattr(cls, "default_model"):
                try:
                    default = cls.default_model(settings)
                except Exception:
                    default = None
            if not specs and getattr(cls, "model_name", ""):
                specs = [fallback_spec(name, cls.model_name)]
            default = default or (specs[0].id if specs else None)

            out.append({
                "provider": name,
                "label": getattr(cls, "label", "") or name,
                "available": available,
                "reason": None if available else (reason or "Unavailable"),
                "models": [s.id for s in specs],
                "specs": [s.to_dict() for s in specs],
                "default_model": default,
                "requires_key": bool(getattr(cls, "requires_key", False)),
            })

        return out
