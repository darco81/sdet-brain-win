"""OCR engine selection — Windows fork.

The Win flagship targets a single 4 GB-VRAM consumer GPU (RTX 3050 Ti
and friends), so the provider matrix is intentionally narrow:

    1. ollama + ocr_ollama_primary_model    ~10-15 s/img on RTX 3050 Ti

There is no MLX-VLM tier (Apple Silicon only) and no Qwen2.5-VL
fallback (32B variant doesn't fit 4 GB VRAM). When ``ollama`` can't
serve the request the call surfaces as ``OCRError`` to the caller.

Tests monkeypatch ``_BUILDERS`` so the chain logic is exercised
without a live Ollama daemon.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from sdet_brain.config import OCRProvider, Settings
from sdet_brain.ocr.protocol import IOCREngine, OCRError

OCREngineBuilder = Callable[[Settings, str], IOCREngine]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OCREngineSelection:
    """Result of ``get_ocr_engine`` — the active engine plus the chain it walked."""

    engine: IOCREngine
    provider: OCRProvider
    model: str
    fell_back: bool
    attempted: tuple[tuple[OCRProvider, str], ...]


def _build_ollama(settings: Settings, model: str) -> IOCREngine:
    """Instantiate the Ollama HTTP provider for the requested model tag."""
    try:
        from sdet_brain.ocr.ollama_provider import OllamaOCREngine
    except ImportError as exc:  # pragma: no cover - defensive
        raise OCRError(
            f"Ollama provider module could not be imported (model={model!r}).",
        ) from exc
    return OllamaOCREngine(
        model_name=model,
        default_prompt=_select_prompt(settings, model),
        quality_min_chars=settings.ocr_quality_min_chars,
        keep_alive=settings.ocr_keep_alive,
        timeout_seconds=settings.ocr_timeout_seconds,
    )


def _select_prompt(settings: Settings, model: str) -> str:
    """Pick grounding vs general prompt by model id."""
    if "deepseek" in model.lower():
        return settings.ocr_grounding_prompt
    return settings.ocr_general_prompt


_BUILDERS: dict[OCRProvider, OCREngineBuilder] = {
    "ollama": _build_ollama,
}


def _resolve_chain(settings: Settings) -> list[tuple[OCRProvider, str]]:
    """Return the ordered ``(provider, model)`` chain for these settings.

    Single-tier on Win: just ``ollama_primary``. The optional fallback
    slot (``ocr_ollama_fallback_model``) lets advanced users add a
    second Ollama model if their hardware can fit one — defaults to
    ``None`` so most installs stay on a single-step chain.
    """
    ollama_primary: tuple[OCRProvider, str] = (
        "ollama",
        settings.ocr_ollama_primary_model,
    )
    chain: list[tuple[OCRProvider, str]] = [ollama_primary]
    if settings.ocr_ollama_fallback_model:
        chain.append(("ollama", settings.ocr_ollama_fallback_model))
    return chain


def _try_build(
    provider: OCRProvider, model: str, settings: Settings
) -> IOCREngine | None:
    builder = _BUILDERS[provider]
    try:
        candidate = builder(settings, model)
    except OCRError as exc:
        logger.warning(
            "OCR provider %s (model=%s) could not be initialised: %s",
            provider,
            model,
            exc,
        )
        return None
    if not candidate.health_check():
        logger.warning(
            "OCR provider %s (model=%s) failed health_check; trying next link.",
            provider,
            model,
        )
        return None
    return candidate


_engine_lock = threading.Lock()
_cached_selection: OCREngineSelection | None = None


def get_ocr_engine(settings: Settings) -> OCREngineSelection:
    """Build the OCR engine, walking the fallback chain on failures."""
    global _cached_selection

    cached = _cached_selection
    if cached is not None:
        return cached

    with _engine_lock:
        cached = _cached_selection
        if cached is not None:
            return cached

        chain = _resolve_chain(settings)
        attempted: list[tuple[OCRProvider, str]] = []
        for provider, model in chain:
            attempted.append((provider, model))
            engine = _try_build(provider, model, settings)
            if engine is None:
                continue
            selection = OCREngineSelection(
                engine=engine,
                provider=provider,
                model=model,
                fell_back=len(attempted) > 1,
                attempted=tuple(attempted),
            )
            _cached_selection = selection
            return selection

        summary = ", ".join(f"{p}:{m}" for p, m in attempted) or "<empty chain>"
        raise OCRError(f"No OCR provider available. Tried: {summary}.")


def reset_ocr_engine() -> None:
    """Drop the cached selection so the next ``get_ocr_engine`` rebuilds."""
    global _cached_selection
    with _engine_lock:
        _cached_selection = None
