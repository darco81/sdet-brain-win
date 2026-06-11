"""Shared fixtures for the server tests.

Tests that exercise the real app lifespan (`create_app` + `TestClient`,
`_build_state`) would otherwise build a real `OllamaEmbedder`, whose
`health_check` opens a live socket to `:11434`. On a dev machine with
Ollama running that socket leaks at GC and pytest reports it as a
`PytestUnraisableExceptionWarning` (an error under
`filterwarnings=error`). Stub the embedder builders so these tests stay
hermetic — no live Ollama/Gemini, deterministic embedder.
"""

from __future__ import annotations

import pytest


class _StubEmbedder:
    vector_size = 1024
    model_name = "stub/embedder"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.vector_size for _ in texts]

    def health_check(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _stub_embedder_builders(monkeypatch: pytest.MonkeyPatch) -> None:
    import sdet_brain.embeddings.factory as factory_module

    monkeypatch.setattr(
        factory_module,
        "_BUILDERS",
        {
            "ollama": lambda _settings: _StubEmbedder(),
            "gemini": lambda _settings: _StubEmbedder(),
        },
    )
