"""Factory chain — Windows fork: Ollama-only, no MLX-VLM tier."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from sdet_brain.config import Settings
from sdet_brain.ocr import factory as factory_module
from sdet_brain.ocr.factory import (
    OCREngineSelection,
    get_ocr_engine,
    reset_ocr_engine,
)
from sdet_brain.ocr.protocol import OCRError, OCRResult


class _StubOCREngine:
    def __init__(self, *, model_name: str, healthy: bool) -> None:
        self._model_name = model_name
        self._healthy = healthy

    @property
    def model_name(self) -> str:
        return self._model_name

    def extract_text(
        self, image_bytes: bytes, *, prompt: str | None = None
    ) -> OCRResult:
        _ = image_bytes
        _ = prompt
        return OCRResult(text="stub", model=self._model_name, duration_s=0.001)

    def health_check(self) -> bool:
        return self._healthy


@pytest.fixture
def patched_builders(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    state: dict[str, Any] = {
        "ollama_primary_healthy": True,
        "ollama_fallback_healthy": True,
    }

    def build_ollama(_: Settings, model: str) -> _StubOCREngine:
        healthy = (
            state["ollama_fallback_healthy"]
            if model.startswith("qwen")
            else state["ollama_primary_healthy"]
        )
        return _StubOCREngine(model_name=f"ollama:{model}", healthy=healthy)

    monkeypatch.setitem(factory_module._BUILDERS, "ollama", build_ollama)
    reset_ocr_engine()
    yield state
    reset_ocr_engine()


def _settings(**overrides: Any) -> Settings:
    return Settings(ocr_provider="ollama", **overrides)


def test_primary_healthy_returns_primary(patched_builders: dict[str, Any]) -> None:
    selection = get_ocr_engine(_settings())
    assert isinstance(selection, OCREngineSelection)
    assert selection.provider == "ollama"
    assert selection.model == "deepseek-ocr"
    assert selection.fell_back is False
    assert selection.attempted == (("ollama", "deepseek-ocr"),)


def test_optional_fallback_used_when_primary_unhealthy(
    patched_builders: dict[str, Any],
) -> None:
    patched_builders["ollama_primary_healthy"] = False
    selection = get_ocr_engine(
        _settings(ocr_ollama_fallback_model="qwen2.5-vl:7b"),
    )
    assert selection.provider == "ollama"
    assert selection.model == "qwen2.5-vl:7b"
    assert selection.fell_back is True
    assert selection.attempted == (
        ("ollama", "deepseek-ocr"),
        ("ollama", "qwen2.5-vl:7b"),
    )


def test_no_fallback_means_single_link_chain_fails_hard(
    patched_builders: dict[str, Any],
) -> None:
    patched_builders["ollama_primary_healthy"] = False
    with pytest.raises(OCRError) as excinfo:
        get_ocr_engine(_settings())
    assert "deepseek-ocr" in str(excinfo.value)
    assert "qwen" not in str(excinfo.value)


def test_all_links_unhealthy_raises(patched_builders: dict[str, Any]) -> None:
    patched_builders["ollama_primary_healthy"] = False
    patched_builders["ollama_fallback_healthy"] = False
    with pytest.raises(OCRError):
        get_ocr_engine(
            _settings(ocr_ollama_fallback_model="qwen2.5-vl:7b"),
        )


def test_singleton_returns_same_instance(patched_builders: dict[str, Any]) -> None:
    first = get_ocr_engine(_settings())
    second = get_ocr_engine(_settings())
    assert first is second
    assert first.engine is second.engine


def test_ocr_error_inherits_from_exception_not_runtime() -> None:
    """Regression: OCRError is a domain error, not an interpreter error.

    Mirrors Mac fork test — keeps the taxonomy explicit across both.
    """
    err = OCRError("boom")
    assert isinstance(err, Exception)
    assert not isinstance(err, RuntimeError)


def test_builder_unexpected_exception_still_falls_back(
    patched_builders: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unexpected exception in a builder (e.g. ConnectionError) must
    NOT crash the chain — `_try_build` logs and tries the next link."""
    def boom_builder(_: Settings, _model: str) -> _StubOCREngine:
        raise ConnectionError("simulated network blip during builder init")

    monkeypatch.setitem(factory_module._BUILDERS, "ollama", boom_builder)
    # With a fallback model, the second ollama link still gets tried.
    # But our builder always raises, so chain is exhausted.
    with pytest.raises(OCRError) as excinfo:
        get_ocr_engine(_settings(ocr_ollama_fallback_model="qwen2.5-vl:7b"))
    # Both links should have been attempted (logged) before raise.
    msg = str(excinfo.value)
    assert "deepseek-ocr" in msg
    assert "qwen2.5-vl:7b" in msg


def test_health_check_exception_treated_as_unhealthy(
    patched_builders: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """If health_check() itself raises, the engine is treated as unhealthy
    rather than crashing the factory."""
    def fragile_builder(_: Settings, model: str) -> _StubOCREngine:
        engine = _StubOCREngine(model_name=model, healthy=True)

        def boom_check() -> bool:
            raise OSError("simulated transport hiccup in health_check")

        engine.health_check = boom_check  # type: ignore[method-assign]
        return engine

    monkeypatch.setitem(factory_module._BUILDERS, "ollama", fragile_builder)
    # Single tier → no fallback → must raise OCRError after one attempt.
    with pytest.raises(OCRError):
        get_ocr_engine(_settings())


def test_reset_ocr_engine_invalidates_cache(
    patched_builders: dict[str, Any],
) -> None:
    """Explicit coverage that reset_ocr_engine forces a fresh chain walk."""
    first = get_ocr_engine(_settings())
    second = get_ocr_engine(_settings())
    assert first is second  # cached

    reset_ocr_engine()
    patched_builders["ollama_primary_healthy"] = False
    with pytest.raises(OCRError):
        # After reset and primary unhealthy + no fallback → fails fresh.
        get_ocr_engine(_settings())
