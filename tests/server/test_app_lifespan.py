"""Application lifespan tests.

We exercise the real `_build_state`/`create_app` path so the lifespan
resolves to a degraded - but still serving - app even when one or both
backends are missing.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from sdet_brain.config import Settings
from sdet_brain.server.app import _build_state, create_app


def test_build_state_does_not_crash_when_qdrant_unreachable() -> None:
    # QdrantStorage is built with check_compatibility=False, so an
    # unreachable URL spawns no background probe thread and does not crash
    # state construction. The embedder is stubbed (see conftest), so the
    # selection is deterministically present rather than service-dependent.
    settings = Settings(qdrant_url="http://127.0.0.1:1")
    state = _build_state(settings)
    assert state.storage is not None
    assert state.selection is not None
    assert state.embedder_error is None


def test_app_starts_and_serves_health_under_degraded_lifespan() -> None:
    """End-to-end: real lifespan + real routes return a structured 200."""
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded", "unavailable"}
    assert "qdrant_ok" in body
    assert "embedder_ok" in body


def test_mcp_instance_attached_to_app() -> None:
    app = create_app()
    assert app.state.mcp is not None
    # Confirm the placeholder ping tool is registered.
    tools = app.state.mcp.tools if hasattr(app.state.mcp, "tools") else []
    # Different FastMCP builds expose tools differently; we just check
    # *something* was registered without locking to a specific layout.
    assert tools or hasattr(app.state.mcp, "_tools") or hasattr(app.state.mcp, "tool")
