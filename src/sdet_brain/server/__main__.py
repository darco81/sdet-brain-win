"""`python -m sdet_brain.server` runs the REST + MCP-HTTP server."""

from __future__ import annotations

import sys

from sdet_brain.server.app import main


def cli() -> int:
    return main()


if __name__ == "__main__":
    sys.exit(cli())
