"""Health endpoint tests using FastAPI's TestClient + injected fakes.

The tests do not need a live Qdrant or MLX runtime - we replace
`AppState` directly so we can drive the four headline scenarios:
fully healthy, only Qdrant up, only embedder up, neither up.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sdet_brain.config import Settings
from sdet_brain.embeddings.factory import EmbedderSelection
from sdet_brain.server.app import create_app
from sdet_brain.server.dependencies import AppState


class _FakeStorage:
    def __init__(self, *, count: int, exists: bool = True) -> None:
        self._count = count
        self._exists = exists

    def count(self, _: str, *, exact: bool = True) -> int:
        return self._count

    def collection_exists(self, _: str) -> bool:
        return self._exists

    def close(self) -> None:
        return None


@dataclass
class _FakeEmbedder:
    healthy: bool = True
    vector_size: int = 8
    model_name: str = "fake/model"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.vector_size for _ in texts]

    def health_check(self) -> bool:
        return self.healthy


def _settings() -> Settings:
    return Settings()


def _state(
    *,
    storage: Any | None,
    embedder: _FakeEmbedder | None,
    qdrant_error: str | None = None,
    embedder_error: str | None = None,
) -> AppState:
    selection = (
        EmbedderSelection(
            embedder=embedder,  # type: ignore[arg-type]
            provider="mlx",
            fell_back=False,
            attempted=("mlx",),
        )
        if embedder is not None
        else None
    )
    return AppState(
        settings=_settings(),
        storage=storage,
        selection=selection,
        qdrant_error=qdrant_error,
        embedder_error=embedder_error,
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_ok_when_state_is_healthy(client: TestClient) -> None:
    client.app.state.app_state = _state(
        storage=_FakeStorage(count=42),
        embedder=_FakeEmbedder(healthy=True, vector_size=1024),
    )
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["qdrant_ok"] is True
    assert body["embedder_ok"] is True
    assert body["embedder_provider"] == "mlx"
    assert body["vector_size"] == 1024
    assert body["collection_count"] == 42


def test_health_degraded_when_qdrant_unavailable(client: TestClient) -> None:
    client.app.state.app_state = _state(
        storage=None,
        embedder=_FakeEmbedder(healthy=True),
        qdrant_error="Connection refused",
    )
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["qdrant_ok"] is False
    assert body["embedder_ok"] is True
    assert body["qdrant_error"] == "Connection refused"


def test_health_degraded_when_embedder_unavailable(client: TestClient) -> None:
    client.app.state.app_state = _state(
        storage=_FakeStorage(count=0),
        embedder=None,
        embedder_error="GEMINI_API_KEY missing",
    )
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["embedder_ok"] is False
    assert body["embedder_error"] == "GEMINI_API_KEY missing"


def test_health_unavailable_when_nothing_works(client: TestClient) -> None:
    client.app.state.app_state = _state(storage=None, embedder=None)
    body = client.get("/health").json()
    assert body["status"] == "unavailable"
    assert body["qdrant_ok"] is False
    assert body["embedder_ok"] is False


def test_openapi_spec_is_exposed(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "SDET Brain"
    paths = spec["paths"]
    assert "/health" in paths
    assert "/status" in paths
    assert "/search" in paths
    assert "/ingest" in paths
