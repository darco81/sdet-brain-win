"""Provider selection with health-check based auto-fallback.

`get_embedder(settings)` reads `EMBEDDING_PROVIDER` and returns an
`IEmbedder` honouring the user's preference. If the primary provider's
`health_check()` fails (e.g. Ollama not running), we fall back to
``gemini`` when its credentials are present.

Windows fork: default is ``ollama`` (bge-m3 via local Ollama server).
``gemini`` stays available as a cloud fallback for the case where
Ollama is down.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sdet_brain.config import EmbeddingProvider, Settings
from sdet_brain.embeddings.gemini_provider import GeminiEmbedder
from sdet_brain.embeddings.ollama_provider import OllamaEmbedder
from sdet_brain.embeddings.protocol import EmbeddingError, IEmbedder

EmbedderBuilder = Callable[[Settings], IEmbedder]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbedderSelection:
    """Result of `get_embedder` - the active provider plus the chain it walked."""

    embedder: IEmbedder
    provider: EmbeddingProvider
    fell_back: bool
    attempted: tuple[EmbeddingProvider, ...]


def _build_ollama(settings: Settings) -> IEmbedder:
    return OllamaEmbedder(
        host=settings.ollama_host,
        model_name=settings.ollama_embed_model,
        batch_size=settings.ollama_batch_size,
        timeout_s=settings.ollama_timeout_s,
    )


def _build_gemini(settings: Settings) -> IEmbedder:
    if not settings.gemini_api_key:
        raise EmbeddingError(
            "Gemini provider requested but GEMINI_API_KEY is not set.",
        )
    return GeminiEmbedder(
        api_key=settings.gemini_api_key,
        model_name=settings.gemini_embedding_model,
        vector_size=settings.gemini_vector_size,
    )


_BUILDERS: dict[EmbeddingProvider, EmbedderBuilder] = {
    "ollama": _build_ollama,
    "gemini": _build_gemini,
}


def _try_build(
    provider: EmbeddingProvider, settings: Settings
) -> IEmbedder | None:
    builder = _BUILDERS.get(provider)
    if builder is None:
        logger.warning("Provider %s is not registered in this build.", provider)
        return None
    try:
        candidate = builder(settings)
    except EmbeddingError as exc:
        logger.warning("Provider %s could not be initialised: %s", provider, exc)
        return None
    if not candidate.health_check():
        logger.warning("Provider %s failed health_check; will try fallback.", provider)
        # OllamaEmbedder owns an httpx.Client that has live sockets after
        # the failed health_check probe. If we just drop the reference we
        # leak the connection until the GC runs (pytest flags this as
        # PytestUnraisableExceptionWarning). Close explicitly.
        close = getattr(candidate, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        return None
    return candidate


def get_embedder(settings: Settings) -> EmbedderSelection:
    """Build an embedding provider, falling back to the alternate on failure."""
    primary = settings.embedding_provider
    secondary: EmbeddingProvider = "gemini" if primary == "ollama" else "ollama"

    attempted: list[EmbeddingProvider] = [primary]
    embedder = _try_build(primary, settings)
    if embedder is not None:
        return EmbedderSelection(
            embedder=embedder,
            provider=primary,
            fell_back=False,
            attempted=tuple(attempted),
        )

    logger.info("Falling back from %s to %s", primary, secondary)
    attempted.append(secondary)
    embedder = _try_build(secondary, settings)
    if embedder is not None:
        return EmbedderSelection(
            embedder=embedder,
            provider=secondary,
            fell_back=True,
            attempted=tuple(attempted),
        )

    raise EmbeddingError(
        f"No embedding provider available. Tried: {', '.join(attempted)}.",
    )
