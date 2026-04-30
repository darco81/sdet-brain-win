"""MCP SSE entrypoint - long-lived connection for remote MCP clients."""

from __future__ import annotations

import logging
import sys

from sdet_brain.config import get_settings
from sdet_brain.server.mcp_server import build_mcp


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    mcp = build_mcp()
    mcp.run(
        transport="sse",
        host=settings.server_host,
        port=settings.mcp_sse_port,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
