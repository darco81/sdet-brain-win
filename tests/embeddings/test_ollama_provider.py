"""Tests for OllamaEmbedder using httpx.MockTransport — no live Ollama needed."""

from __future__ import annotations

import contextlib
import json
from typing import Any

import httpx
import pytest

from sdet_brain.embeddings.ollama_provider import OllamaEmbedder
from sdet_brain.embeddings.protocol import EmbeddingError, IEmbedder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(base_url="http://localhost:11434", transport=handler)


def _ok_handler(
    *,
    dim: int = 1024,
    vectors_per_call: int | None = None,
) -> httpx.MockTransport:
    """Return a transport that echoes a fixed-dim vector per input.

    If ``vectors_per_call`` is set, the returned ``embeddings`` list is
    truncated/padded to that length — useful for simulating Ollama
    returning the wrong number of vectors.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        body = json.loads(request.content)
        inputs = body["input"]
        count = vectors_per_call if vectors_per_call is not None else len(inputs)
        vectors = [[0.1 * (i + 1)] * dim for i in range(count)]
        return httpx.Response(200, json={"embeddings": vectors})

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_implements_iembedder_protocol() -> None:
    embedder = OllamaEmbedder(client=_make_client(_ok_handler()))
    assert isinstance(embedder, IEmbedder)


def test_empty_input_returns_empty_list() -> None:
    embedder = OllamaEmbedder(client=_make_client(_ok_handler()))
    assert embedder.embed([]) == []


def test_single_text_returns_one_vector_of_expected_dim() -> None:
    embedder = OllamaEmbedder(client=_make_client(_ok_handler(dim=1024)))
    out = embedder.embed(["hello"])
    assert len(out) == 1
    assert len(out[0]) == 1024


def test_vector_size_property_probes_when_unknown() -> None:
    embedder = OllamaEmbedder(client=_make_client(_ok_handler(dim=768)))
    # Property access triggers a probe call.
    assert embedder.vector_size == 768


def test_batching_splits_into_chunks_of_batch_size() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(len(body["input"]))
        return httpx.Response(
            200,
            json={"embeddings": [[0.1] * 4 for _ in body["input"]]},
        )

    embedder = OllamaEmbedder(
        batch_size=3,
        client=_make_client(httpx.MockTransport(handler)),
    )
    out = embedder.embed(["a", "b", "c", "d", "e", "f", "g"])
    assert len(out) == 7
    assert calls == [3, 3, 1]


def test_health_check_returns_true_when_probe_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # health_check() does a real socket.create_connection TCP precheck before
    # the HTTP probe; stub it so the test stays hermetic (no live Ollama).
    monkeypatch.setattr(
        "sdet_brain.embeddings.ollama_provider.socket.create_connection",
        lambda *args, **kwargs: contextlib.nullcontext(),
    )
    embedder = OllamaEmbedder(client=_make_client(_ok_handler()))
    assert embedder.health_check() is True


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_http_error_raises_embedding_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="ollama meltdown")

    embedder = OllamaEmbedder(
        client=_make_client(httpx.MockTransport(handler)),
    )
    with pytest.raises(EmbeddingError, match="Ollama embed call failed"):
        embedder.embed(["x"])


def test_non_json_body_raises_embedding_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    embedder = OllamaEmbedder(
        client=_make_client(httpx.MockTransport(handler)),
    )
    with pytest.raises(EmbeddingError, match="non-JSON"):
        embedder.embed(["x"])


def test_missing_embeddings_key_raises_embedding_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "bge-m3"})

    embedder = OllamaEmbedder(
        client=_make_client(httpx.MockTransport(handler)),
    )
    with pytest.raises(EmbeddingError, match="malformed embeddings"):
        embedder.embed(["x"])


def test_wrong_vector_count_raises_embedding_error() -> None:
    # Server returns 2 vectors for a single-input batch.
    embedder = OllamaEmbedder(
        client=_make_client(_ok_handler(vectors_per_call=2)),
    )
    with pytest.raises(EmbeddingError, match="malformed embeddings"):
        embedder.embed(["x"])


def test_empty_vector_raises_embedding_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[]]})

    embedder = OllamaEmbedder(
        client=_make_client(httpx.MockTransport(handler)),
    )
    with pytest.raises(EmbeddingError, match="empty/non-list vector"):
        embedder.embed(["x"])


def test_vector_size_drift_raises_after_first_call() -> None:
    state: dict[str, Any] = {"call": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        state["call"] += 1
        dim = 1024 if state["call"] == 1 else 768  # second call drifts
        return httpx.Response(200, json={"embeddings": [[0.1] * dim]})

    embedder = OllamaEmbedder(
        client=_make_client(httpx.MockTransport(handler)),
    )
    embedder.embed(["first"])  # caches dim=1024
    with pytest.raises(EmbeddingError, match="vector_size drift"):
        embedder.embed(["second"])


def test_health_check_returns_false_on_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    embedder = OllamaEmbedder(
        client=_make_client(httpx.MockTransport(handler)),
    )
    assert embedder.health_check() is False


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_context_manager_closes_owned_client() -> None:
    client = _make_client(_ok_handler())
    with OllamaEmbedder(client=client) as embedder:
        # Owns the injected client? No — we passed it in.
        assert embedder.embed(["x"])
    # Externally-owned client should still be open after exit.
    assert not client.is_closed


def test_context_manager_closes_default_owned_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Don't actually try to talk to a real server; intercept the
    # implicit httpx.Client construction.
    real_client = _make_client(_ok_handler())
    monkeypatch.setattr(
        "sdet_brain.embeddings.ollama_provider.httpx.Client",
        lambda **kwargs: real_client,
    )
    with OllamaEmbedder() as embedder:
        assert embedder.embed(["x"])
    assert real_client.is_closed
