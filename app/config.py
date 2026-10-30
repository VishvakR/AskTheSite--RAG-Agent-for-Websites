"""
Centralised application configuration.

Replaces the scattered ``os.getenv`` calls and hardcoded literals that used to
live across the storage providers, the crawler and ``server.py``.  Everything
is read once, validated, and exposed through the cached :func:`get_settings`.
"""

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Storage ───────────────────────────────────────────────────────────
    persistent_storage: Path = Field(
        Path("./storage/cache"),
        validation_alias="PERSISTENT_STORAGE",
        description="Directory backing the Chroma vector index.",
    )
    catalog_db: Path = Field(
        Path("./storage/askthesite.db"),
        validation_alias="CATALOG_DB",
        description="SQLite file holding workspaces, jobs and query history.",
    )
    workspace_root: Path = Field(
        Path("./workspaces"),
        validation_alias="WORKSPACE_ROOT",
        description="Root for crawled markdown, one subdirectory per workspace.",
    )

    # ── Embeddings / reranking ────────────────────────────────────────────
    embedding_model: str = Field(
        "sentence-transformers/all-MiniLM-L6-v2",
        validation_alias="EMBEDDING_MODEL",
    )
    embedding_cache: Path = Field(Path("./cache"), validation_alias="EMBEDDING_CACHE")
    rerank_model: str = Field(
        "cross-encoder/ms-marco-MiniLM-L-6-v2",
        validation_alias="RERANK_MODEL",
    )

    # ── LLM ───────────────────────────────────────────────────────────────
    # Deliberately a plain str, not a Literal: providers are registered at
    # runtime through LanguageModelFactory, which validates the name and
    # reports the available ones. Hardcoding the set here would reject any
    # provider added to the registry.
    llm_provider: str = Field("opensource", validation_alias="LLM_PROVIDER")
    llm_model: str = Field("qwen3.5:4b-mlx", validation_alias="LLM_MODEL")
    llm_temperature: float = Field(0.7, ge=0.0, le=2.0, validation_alias="LLM_TEMPERATURE")

    ollama_base_url: str = Field(
        "http://localhost:11434", validation_alias="OLLAMA_BASE_URL"
    )
    anthropic_api_key: Optional[str] = Field(None, validation_alias="ANTHROPIC_API_KEY")
    openai_api_key: Optional[str] = Field(None, validation_alias="OPENAI_API_KEY")

    # ── Crawling ──────────────────────────────────────────────────────────
    crawl_headless: bool = Field(True, validation_alias="CRAWL_HEADLESS")
    crawl_max_pages: int = Field(100, ge=1, validation_alias="CRAWL_MAX_PAGES")
    crawl_max_depth: int = Field(3, ge=0, validation_alias="CRAWL_MAX_DEPTH")
    crawl_concurrency: int = Field(8, ge=1, validation_alias="CRAWL_CONCURRENCY")
    max_concurrent_jobs: int = Field(2, ge=1, validation_alias="MAX_CONCURRENT_JOBS")

    # ── Chunking ──────────────────────────────────────────────────────────
    chunk_size: int = Field(1000, ge=100, validation_alias="CHUNK_SIZE")
    chunk_overlap: int = Field(200, ge=0, validation_alias="CHUNK_OVERLAP")

    # ── Observability / misc ──────────────────────────────────────────────
    phoenix_api_key: Optional[str] = Field(None, validation_alias="PHOENIX_API_KEY")
    log_level: str = Field("INFO", validation_alias="LOG_LEVEL")
    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        validation_alias="CORS_ORIGINS",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        """Accept a comma-separated string as well as a real list."""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("persistent_storage", "workspace_root", "embedding_cache")
    @classmethod
    def _ensure_dir(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v

    @field_validator("catalog_db")
    @classmethod
    def _ensure_parent(cls, v: Path) -> Path:
        v.parent.mkdir(parents=True, exist_ok=True)
        return v

    def workspace_dir(self, workspace_id: str) -> Path:
        """Directory holding one workspace's crawled pages and manifest."""
        return self.workspace_root / workspace_id

    def api_key_for(self, provider: str) -> Optional[str]:
        return {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
        }.get(provider)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
