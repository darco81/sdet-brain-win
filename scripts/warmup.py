"""Pre-download fastembed reranker + Ollama embed model.

Run this once after `uv sync` so the first MCP server boot doesn't
spend 30-60 seconds downloading the reranker model. Claude Desktop's
stdio handshake can time out on a cold-start that's that slow.

What gets downloaded:
- `jinaai/jina-reranker-v2-base-multilingual` via fastembed (~500 MB
  ONNX). Cached under ~/.cache/fastembed/ (or
  %LOCALAPPDATA%\\fastembed\\ on Windows).
- (Optional) bge-m3 via Ollama if you didn't `ollama pull bge-m3` yet.

Usage:
    uv run python scripts/warmup.py

Idempotent — re-running on an already-warm cache is a no-op (cache hit).
"""

from __future__ import annotations

import os
import sys

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]


def warm_reranker() -> int:
    """Load the cross-encoder so fastembed downloads + caches the ONNX file."""
    try:
        from sdet_brain.embeddings.reranker import RerankCandidate, get_reranker
    except Exception as exc:
        print(f"  reranker import failed: {exc}", file=sys.stderr)
        return 1
    try:
        rerank = get_reranker()
        # Force lazy load by scoring two dummy candidates.
        rerank.rerank(
            "warmup probe",
            [
                RerankCandidate(text="a", payload=None),
                RerankCandidate(text="b", payload=None),
            ],
        )
    except Exception as exc:
        print(f"  reranker warmup FAILED: {exc}", file=sys.stderr)
        return 1
    print("  reranker: OK (cached)")
    return 0


def warm_ollama() -> int:
    """Probe Ollama; if bge-m3 not present, instruct user to pull it."""
    if httpx is None:
        print("  ollama: SKIP (httpx not installed — run uv sync first)")
        return 1
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(f"{host}/api/tags")
            r.raise_for_status()
            models = r.json().get("models", [])
    except Exception as exc:
        print(f"  ollama: UNREACHABLE at {host} ({exc})")
        print("  -> start Ollama: open the app or run `ollama serve`")
        return 1
    names = [m.get("name", "") for m in models]
    target = os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3")
    if any(target in n for n in names):
        print(f"  ollama: OK ({target} pulled)")
        return 0
    print(f"  ollama: model {target} NOT pulled — run `ollama pull {target}`")
    return 1


def main() -> int:
    print("sdet-brain-win warmup")
    print("=" * 40)
    print("Reranker (fastembed ONNX, ~500 MB first download)...")
    rc_a = warm_reranker()
    print()
    print("Ollama embedding model...")
    rc_b = warm_ollama()
    print()
    if rc_a == 0 and rc_b == 0:
        print("All green. MCP server cold-start should now be fast.")
        return 0
    print("Some warmup steps failed — see messages above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
