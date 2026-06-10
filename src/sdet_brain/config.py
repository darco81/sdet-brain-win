"""Application configuration loaded from environment variables.

All settings are read from environment or `.env` file via pydantic-settings.
See `.env.example` for the full list of supported variables.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

EmbeddingProvider = Literal["ollama", "gemini"]
OCRProvider = Literal["ollama"]


class Settings(BaseSettings):
    """Runtime settings for the SDET Brain server."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Qdrant ---
    qdrant_url: str = Field(
        default="http://localhost:6333",
        description="Qdrant HTTP endpoint.",
    )
    qdrant_api_key: str | None = Field(
        default=None,
        description="Optional Qdrant API key (production deploys).",
    )
    collection_name: str = Field(
        default="sdet_brand_v1",
        description="Primary Qdrant collection for the brand corpus.",
    )

    # --- Embeddings ---
    embedding_provider: EmbeddingProvider = Field(
        default="ollama",
        description="Primary embedding provider. Falls back to the other on failure.",
    )
    # Ollama settings (provider class lands in P2)
    ollama_host: str = Field(
        default="http://localhost:11434",
        description="Local Ollama server URL.",
    )
    ollama_embed_model: str = Field(
        default="bge-m3",
        description="Ollama model id used for embeddings (1024-dim).",
    )
    ollama_batch_size: int = Field(default=16)
    ollama_timeout_s: float = Field(default=60.0)
    # Cloud fallback / placeholder until P2
    gemini_api_key: str | None = Field(
        default=None,
        description="Google Gemini API key (used for fallback or pre-P2 testing).",
    )
    gemini_embedding_model: str = Field(
        default="text-embedding-004",
        description="Gemini embedding model id.",
    )
    gemini_vector_size: int = Field(
        default=768,
        description="Output dimensionality for the Gemini embedding model.",
    )

    # --- Server ---
    server_host: str = Field(default="127.0.0.1")
    server_port: int = Field(default=8080)
    mcp_sse_port: int = Field(default=8081)
    log_level: str = Field(default="INFO")

    # --- Ingestion ---
    chunk_target_chars: int = Field(default=800)
    chunk_overlap_ratio: float = Field(default=0.15)
    embed_batch_size: int = Field(default=32)
    watch_paths: str = Field(
        default="",
        description="Comma-separated absolute paths the watcher monitors.",
    )
    watcher_debounce_ms: int = Field(default=300)

    # --- Brand corpus source paths (per source_type) ---
    # Each is a comma-separated list of absolute directories. CLI
    # handlers (ingest, watcher) consume these to wire up the source
    # classifier. Empty means "no roots registered for that
    # source_type" - files outside all roots tag as `unknown`.
    project_knowledge_paths: str = Field(
        default="",
        description="Comma-separated paths whose 01-PROJECT-CONTEXT/etc files map to project-knowledge.",
    )
    drafts_paths: str = Field(
        default="",
        description="Comma-separated paths to draft Markdown trees.",
    )
    articles_paths: str = Field(
        default="",
        description="Comma-separated paths to published article trees.",
    )
    sprint_reports_paths: str = Field(
        default="",
        description="Comma-separated paths to sprint-report directories.",
    )
    brief_paths: str = Field(
        default="",
        description="Comma-separated paths to brief / spec / methodology trees.",
    )

    # --- Reranking (T2-04) ---
    rerank_enabled: bool = Field(
        default=False,
        description="When True, search re-orders candidates with a cross-encoder before returning.",
    )
    rerank_model: str = Field(
        default="jinaai/jina-reranker-v2-base-multilingual",
        description="Cross-encoder model id (must be in fastembed's CROSS_ENCODER_REGISTRY).",
    )
    rerank_top_k_retrieve: int = Field(
        default=30,
        description="How many candidates to over-fetch from Qdrant before reranking.",
    )
    rerank_top_k_return: int = Field(
        default=5,
        description="Top-K to return after reranking.",
    )

    # --- Local LLM ---
    # Windows fork: LLM digest is disabled by design. 4 GB VRAM target can't
    # fit even a small Qwen LLM alongside the embedder. Use a separate
    # external service (e.g. Gemini API utility) if you need digests later.

    # --- OCR (0.2.0-win.0) ---
    ocr_provider: OCRProvider = Field(
        default="ollama",
        description=(
            "Primary OCR backend. Win flagship: ``ollama`` only — MLX-VLM "
            "is Apple Silicon, dropped from this fork."
        ),
    )
    ocr_ollama_primary_model: str = Field(
        default="deepseek-ocr",
        description="Ollama model tag used as the primary OCR model.",
    )
    ocr_ollama_fallback_model: str | None = Field(
        default=None,
        description=(
            "Optional secondary Ollama model. Defaults to ``None`` because "
            "the 4 GB VRAM target cannot fit qwen2.5-vl:32b (~22 GB) — set "
            "to a lighter model name if your hardware has headroom."
        ),
    )
    ocr_timeout_seconds: int = Field(
        default=120,
        ge=1,
        description="Wall-clock cap for a single OCR call before ``OCRTimeoutError``.",
    )
    ocr_max_image_dim: int = Field(
        default=1600,
        ge=64,
        description="Resize budget — long edge clamped to this many pixels before OCR.",
    )
    ocr_max_image_bytes: int = Field(
        default=20_000_000,
        ge=1,
        description="Hard ceiling on input image size; bigger payloads are rejected.",
    )
    ocr_max_pdf_pages: int = Field(
        default=20,
        ge=1,
        description="Hard ceiling on PDF page count; longer documents are rejected.",
    )
    ocr_keep_alive: str = Field(
        default="5m",
        description=(
            "Ollama ``keep_alive`` directive — how long the model stays "
            "loaded after the last request. Short on Win to release "
            "the limited 4 GB VRAM between calls."
        ),
    )
    ocr_quality_min_chars: int = Field(
        default=50,
        ge=0,
        description=(
            "Below this character count (after grounding-token strip) the "
            "provider raises ``OCRQualityError`` and the factory tries the "
            "next link in the fallback chain."
        ),
    )
    ocr_pii_scrub: bool = Field(
        default=False,
        description=(
            "Feature flag for post-OCR PII scrubbing. Off in MVP; hook reserved for 0.3.0-win."
        ),
    )
    ocr_grounding_prompt: str = Field(
        default="<|grounding|>Convert the document to markdown.",
        description="Prompt fed to DeepSeek-OCR variants — uses the grounding token.",
    )
    ocr_general_prompt: str = Field(
        default=(
            "Extract all text from this image and return it as markdown. "
            "Preserve layout and structure."
        ),
        description="Prompt fed to general VLMs that lack the grounding token.",
    )


def parse_path_list(value: str) -> list[str]:
    """Split a comma-separated env var into a clean list of paths."""
    return [item.strip() for item in value.split(",") if item.strip()]


def get_settings() -> Settings:
    """Return a cached Settings instance.

    The function is intentionally a thin wrapper so callers can monkeypatch
    it in tests without poking at the global module state.
    """
    return Settings()


def project_root() -> Path:
    """Return the repository root path on disk."""
    return Path(__file__).resolve().parents[2]
