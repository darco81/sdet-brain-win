"""MCP stdio entrypoint - the transport Claude Desktop uses."""

from __future__ import annotations

import logging
import sys

from sdet_brain.config import get_settings
from sdet_brain.server.mcp_server import build_mcp
from sdet_brain.server.state import build_default_state


def _force_utf8_streams() -> None:
    # Markdown chunks contain em-dashes (U+2014), Polish diacritics, smart
    # quotes. Python on Windows defaults stdout to cp1252; FastMCP serialises
    # tool results with ensure_ascii=False, so non-ASCII bytes hit the wire
    # encoded as mojibake and Claude Desktop receives garbage snippets. Force
    # UTF-8 on both ends of the stdio transport.
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main() -> int:
    _force_utf8_streams()
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
        # stdio transport reserves stdout for the protocol; logs go to stderr.
        stream=sys.stderr,
    )
    state = build_default_state(settings)
    mcp = build_mcp(state_getter=lambda: state)
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
