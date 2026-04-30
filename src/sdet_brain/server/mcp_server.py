"""FastMCP wrapper exposing the SDET Brain server as MCP tools.

T1-06 ships a minimal `ping` placeholder so the three transports
(stdio / SSE / streamable HTTP) can be smoke-tested. T1-07 adds the
real tool surface (search, ingest, list_sources, get_chunk_neighbors).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def build_mcp() -> FastMCP:
    """Construct the FastMCP instance with the placeholder tools."""
    mcp: FastMCP = FastMCP(
        name="sdet-brain",
        instructions=(
            "Persistent RAG for the SDET brand domain. Tools land in T1-07; "
            "the current build only exposes a `ping` smoke-test."
        ),
    )

    @mcp.tool
    def ping() -> dict[str, str]:
        """Return a cheap liveness check that confirms the MCP transport works."""
        return {"status": "ok", "service": "sdet-brain"}

    return mcp
