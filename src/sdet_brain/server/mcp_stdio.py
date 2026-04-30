"""MCP stdio entrypoint - the transport Claude Desktop uses."""

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
        # stdio transport reserves stdout for the protocol; logs go to stderr.
        stream=sys.stderr,
    )
    mcp = build_mcp()
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
