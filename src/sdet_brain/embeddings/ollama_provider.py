"""Embedding provider backed by a local Ollama server (HTTP).

Ollama must be running locally (``ollama serve``) with the chosen
model pulled (``ollama pull bge-m3``). Vector size is detected from
the first inference response and cached for the lifetime of the
instance.

Designed for the Windows + CUDA fork: bge-m3 on RTX 3050 4 GB VRAM
yields ~440 MB VRAM usage in Q4 GGUF (Ollama default). The class
implements the same :class:`IEmbedder` protocol as the upstream Mac
``MLXEmbedder``, so the factory/server code path is identical.
"""

from __future__ import annotations

import logging
from typing import Final

import httpx

from sdet_brain.embeddings.protocol import EmbeddingError

logger = logging.getLogger("sdet_brain.embeddings.ollama")

DEFAULT_HOST: Final[str] = "http://localhost:11434"
DEFAULT_MODEL: Final[str] = "bge-m3"
DEFAULT_BATCH_SIZE: Final[int] = 16
DEFAULT_TIMEOUT_S: Final[float] = 60.0


class OllamaEmbedder:
    """Embedding provider that talks to a local Ollama server over HTTP.

    Args:
        host: Base URL of the Ollama service. Default ``http://localhost:11434``.
        model_name: HuggingFace-style id of the embedding model (e.g.
            ``bge-m3``). The model must be pulled in Ollama beforehand.
        batch_size: How many texts to send per HTTP request. Ollama's
            ``/api/embed`` accepts a list, so this is purely a chunking
            tradeoff between request count and per-request memory.
        timeout_s: Per-request HTTP timeout. Large enough to cover cold
            model load on the first call (bge-m3 cold-loads in ~5-10s on
            RTX 3050).
        client: Optional pre-built httpx.Client. Use this to inject a
            ``MockTransport`` from tests, or to share connection pooling
            from a wider context. When omitted, a private client is
            owned by this instance and closed by :meth:`close`.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        model_name: str = DEFAULT_MODEL,
        batch_size: int = DEFAULT_BATCH_SIZE,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
    ) -> None:
        self._host = host.rstrip("/")
        self._model_name = model_name
        self._batch_size = batch_size
        self._timeout = timeout_s
        self._vector_size: int | None = None
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            self._client = httpx.Client(base_url=self._host, timeout=self._timeout)
            self._owns_client = True

    # ------------------------------------------------------------------
    # IEmbedder protocol
    # ------------------------------------------------------------------

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def vector_size(self) -> int:
        if self._vector_size is None:
            # Probe with a tiny input so the dim is known without ingest.
            self.embed(["probe"])
        assert self._vector_size is not None  # noqa: S101 — populated above
        return self._vector_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        results: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            payload = {"model": self._model_name, "input": batch}
            try:
                resp = self._client.post("/api/embed", json=payload)
                resp.raise_for_status()
                body = resp.json()
            except httpx.HTTPError as exc:
                raise EmbeddingError(
                    f"Ollama embed call failed against {self._host!r}: {exc}"
                ) from exc
            except ValueError as exc:
                raise EmbeddingError(
                    f"Ollama returned non-JSON body from {self._host!r}: {exc}"
                ) from exc

            embeddings = body.get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) != len(batch):
                raise EmbeddingError(
                    f"Ollama returned malformed embeddings for batch of "
                    f"{len(batch)} (model={self._model_name!r}): {body!r}"
                )
            # Defensive cast — Ollama returns lists of floats, but a
            # numerical-typed nested list is what the rest of the
            # pipeline expects.
            for vec in embeddings:
                if not isinstance(vec, list) or not vec:
                    raise EmbeddingError(
                        f"Ollama returned empty/non-list vector "
                        f"(model={self._model_name!r}): {vec!r}"
                    )
                results.append([float(x) for x in vec])

        if self._vector_size is None and results:
            self._vector_size = len(results[0])
            logger.info(
                "OllamaEmbedder vector_size detected: %d (model=%s)",
                self._vector_size,
                self._model_name,
            )
        elif self._vector_size is not None and results:
            # Catch silent dim drift if someone repulls a different model
            # under the same Ollama name.
            if len(results[0]) != self._vector_size:
                raise EmbeddingError(
                    f"Ollama vector_size drift: expected {self._vector_size}, "
                    f"got {len(results[0])} (model={self._model_name!r})"
                )
        return results

    def health_check(self) -> bool:
        try:
            output = self.embed(["sdet-brain health probe"])
        except Exception:
            logger.warning("Ollama health check failed", exc_info=True)
            return False
        return len(output) == 1 and self._vector_size is not None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OllamaEmbedder:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
