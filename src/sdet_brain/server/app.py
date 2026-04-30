"""FastAPI application factory.

`create_app()` builds the app and wires its lifespan: Qdrant + embedder
construction at startup, graceful close on shutdown. Failures during
startup are logged and reported through `/health` rather than crashing
the process - the server stays useful enough to surface its own
problems.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from sdet_brain.config import Settings, get_settings
from sdet_brain.embeddings.factory import get_embedder
from sdet_brain.embeddings.protocol import EmbeddingError
from sdet_brain.server.dependencies import AppState
from sdet_brain.server.mcp_server import build_mcp
from sdet_brain.server.routes.health import router as health_router
from sdet_brain.server.routes.ingest import router as ingest_router
from sdet_brain.server.routes.search import router as search_router
from sdet_brain.server.routes.status import router as status_router
from sdet_brain.storage.qdrant_client import QdrantStorage

logger = logging.getLogger("sdet_brain.server")


def _build_state(settings: Settings) -> AppState:
    state = AppState(settings=settings, storage=None, selection=None)
    try:
        state.storage = QdrantStorage(settings.qdrant_url, api_key=settings.qdrant_api_key)
    except Exception as exc:
        state.qdrant_error = str(exc)
        logger.warning("Qdrant unavailable at startup: %s", exc)

    try:
        state.selection = get_embedder(settings)
    except EmbeddingError as exc:
        state.embedder_error = str(exc)
        logger.warning("Embedder unavailable at startup: %s", exc)
    return state


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    state = _build_state(settings)
    app.state.app_state = state
    logger.info(
        "Server ready (qdrant_ok=%s, embedder_ok=%s)",
        state.storage is not None,
        state.embedder is not None,
    )
    try:
        yield
    finally:
        if state.storage is not None:
            state.storage.close()
        logger.info("Server shutdown complete")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a FastAPI app with the SDET Brain routes and FastMCP mount."""
    settings = settings or get_settings()
    mcp = build_mcp()
    app = FastAPI(
        title="SDET Brain",
        version="0.1.0",
        description="Persistent RAG for the SDET brand domain.",
        lifespan=_lifespan,
    )

    app.include_router(health_router)
    app.include_router(status_router)
    app.include_router(search_router)
    app.include_router(ingest_router)

    # Mount the FastMCP streamable HTTP transport so any client that
    # speaks MCP-over-HTTP can reach the same tools as the stdio/SSE
    # entrypoints. The `lifespan` parameter on `http_app` ensures
    # FastMCP's own startup hooks fire under FastAPI's lifespan.
    app.mount("/mcp", mcp.http_app(transport="streamable-http"))

    # Stash the FastMCP instance on the app so tests / future tooling
    # can introspect registered tools without re-building it.
    app.state.mcp = mcp

    _ = settings  # kept for symmetry with future per-instance config wiring
    return app


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    uvicorn.run(
        "sdet_brain.server.app:create_app",
        host=settings.server_host,
        port=settings.server_port,
        factory=True,
        log_level=settings.log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
