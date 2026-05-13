"""Daily corpus reingest + health check for sdet-brain-win on Windows.

Replacement for the upstream Mac ``scripts/daily.sh``. Pure Python so
the same script works under Windows Task Scheduler, WSL, Linux cron,
or a manual ``python scripts/daily.py`` invocation.

Memory guard: parses ``psutil.virtual_memory()`` and skips the run
when available RAM is below ``INGEST_MIN_GB`` (default 8 GB on the
RTX 3050 Ti / 32 GB RAM reference machine — Mac's 20 GB threshold
doesn't fit).

Routes ingest through the already-running server's ``POST /ingest``
endpoint (single Ollama instance, no duplicate model in CLI) and
optionally takes a Qdrant collection snapshot when
``QDRANT_SNAPSHOT_ENABLED=true``.

Configuration is via environment variables — see ``.env.example``
in the repo root for the full list. Logs go to ``DAILY_LOG``
(default ``%LOCALAPPDATA%\\sdet-brain\\daily.log`` on Windows,
``~/.local/state/sdet-brain/daily.log`` on POSIX).
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import httpx
import psutil

# ---------------------------------------------------------------------------
# Defaults / env parsing
# ---------------------------------------------------------------------------

DEFAULT_INGEST_MIN_GB = 8
DEFAULT_SERVER_URL = "http://localhost:8080"
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_COLLECTION = "sdet_brand_v1"
DEFAULT_PATH_SEPARATOR = ";" if os.name == "nt" else ":"

INGEST_TIMEOUT_S = 1800  # 30 min hard ceiling per path
EXCLUDE_DIRS = ["node_modules", "__pycache__", ".claude", ".git"]


def _state_dir() -> Path:
    """Return per-OS writable state directory for logs + snapshots."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(base) / "sdet-brain"
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / "sdet-brain"


def _setup_logging() -> logging.Logger:
    state_dir = _state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(os.environ.get("DAILY_LOG", str(state_dir / "daily.log")))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler: logging.Handler = RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(fmt)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)

    logger = logging.getLogger("sdet-brain-daily")
    logger.setLevel(logging.INFO)
    logger.handlers = [handler, console]
    logger.propagate = False
    return logger


# ---------------------------------------------------------------------------
# Toast notification (Windows-only, best-effort)
# ---------------------------------------------------------------------------


def _notify_toast(title: str, body: str, ok: bool) -> None:
    """Show a Windows toast. No-op on other OSes or when package missing."""
    if os.name != "nt":
        return
    try:
        from windows_toasts import Toast, WindowsToaster  # type: ignore[import-not-found]
    except ImportError:
        return
    try:
        toaster = WindowsToaster("sdet-brain")
        notification = Toast()
        notification.text_fields = [title, body]
        toaster.show_toast(notification)
    except Exception:
        # Toast is purely informational — failure here must not abort the run.
        pass
    _ = ok  # reserved for future variant (success vs. fail icon)


# ---------------------------------------------------------------------------
# Health probes
# ---------------------------------------------------------------------------


def _free_gb() -> float:
    return psutil.virtual_memory().available / 1_073_741_824


def _disk_free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1_073_741_824


def _server_reachable(url: str, timeout_s: float = 3.0) -> bool:
    try:
        with httpx.Client(timeout=timeout_s) as client:
            return client.get(f"{url}/health").status_code == 200
    except Exception:
        return False


def _qdrant_reachable(url: str, timeout_s: float = 3.0) -> bool:
    try:
        with httpx.Client(timeout=timeout_s) as client:
            r = client.get(f"{url}/readyz")
            return r.status_code == 200 and "all shards are ready" in r.text
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Idle / power guard
# ---------------------------------------------------------------------------


def _ac_powered() -> bool:
    """True if AC plugged in OR desktop (no battery)."""
    battery = psutil.sensors_battery()
    if battery is None:
        return True  # desktop
    return bool(battery.power_plugged)


def _gpu_busy() -> bool:
    """Heuristic: is anything heavy on the GPU? Returns False on missing nvidia-smi."""
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        import subprocess  # noqa: S404 — local trusted invocation

        out = subprocess.check_output(  # noqa: S603
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            text=True,
            timeout=5,
        )
        utils = [int(x.strip()) for x in out.strip().splitlines() if x.strip().isdigit()]
        return max(utils, default=0) > 50
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Ingest via HTTP
# ---------------------------------------------------------------------------


def _post_ingest(server_url: str, path: str, logger: logging.Logger) -> tuple[bool, int]:
    body = {"path": path, "force": False, "exclude_dirs": EXCLUDE_DIRS}
    logger.info("ingest start: %s", path)
    try:
        with httpx.Client(timeout=INGEST_TIMEOUT_S) as client:
            resp = client.post(f"{server_url}/ingest", json=body)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        # ValueError covers json.JSONDecodeError — server returned 200
        # with malformed body, or a proxy returned HTML. Either way the
        # ingest didn't happen and we shouldn't pretend it did.
        logger.error("ingest FAIL %s: %s", path, exc)
        return False, 0
    chunks = int(data.get("chunks_created", 0))
    errors = data.get("errors") or []
    if errors:
        logger.warning("ingest %s reported %d row-level errors", path, len(errors))
        return False, chunks
    logger.info(
        "ingest OK %s: files=%s skipped=%s chunks=%s",
        path,
        data.get("files_processed"),
        data.get("files_skipped"),
        chunks,
    )
    return True, chunks


# ---------------------------------------------------------------------------
# Qdrant snapshot
# ---------------------------------------------------------------------------


def _snapshot_qdrant(qdrant_url: str, collection: str, logger: logging.Logger) -> None:
    try:
        with httpx.Client(timeout=120) as client:
            r = client.post(f"{qdrant_url}/collections/{collection}/snapshots")
            r.raise_for_status()
            snap = r.json()["result"]
            logger.info("qdrant snapshot created: %s (%s bytes)", snap["name"], snap.get("size", "?"))
    except Exception as exc:
        logger.warning("qdrant snapshot FAIL: %s", exc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_paths_env(value: str) -> list[str]:
    return [item.strip() for item in value.split(DEFAULT_PATH_SEPARATOR) if item.strip()]


def _collect_paths() -> list[str]:
    """Combine the per-source-type env vars used by sdet-brain config."""
    paths: list[str] = []
    for var in (
        "DRAFTS_PATHS",
        "ARTICLES_PATHS",
        "PROJECT_KNOWLEDGE_PATHS",
        "SPRINT_REPORTS_PATHS",
        "BRIEF_PATHS",
    ):
        raw = os.environ.get(var, "")
        for p in _parse_paths_env(raw):
            if p not in paths and Path(p).is_dir():
                paths.append(p)
    # Backwards-compat: also accept CORPUS_PATHS as a flat semicolon list.
    for p in _parse_paths_env(os.environ.get("CORPUS_PATHS", "")):
        if p not in paths and Path(p).is_dir():
            paths.append(p)
    return paths


def main() -> int:
    logger = _setup_logging()
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    logger.info("=== daily start %s (%s) ===", started, socket.gethostname())

    ingest_min_gb = float(os.environ.get("INGEST_MIN_GB", DEFAULT_INGEST_MIN_GB))
    server_url = os.environ.get("SDET_BRAIN_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/")
    qdrant_url = os.environ.get("QDRANT_URL", DEFAULT_QDRANT_URL).rstrip("/")
    collection = os.environ.get("COLLECTION_NAME", DEFAULT_COLLECTION)
    snapshot_enabled = os.environ.get("QDRANT_SNAPSHOT_ENABLED", "false").lower() in {"1", "true", "yes"}
    respect_idle = os.environ.get("RESPECT_USER_IDLE", "true").lower() in {"1", "true", "yes"}

    # --- Memory guard ---
    free_gb = _free_gb()
    if free_gb < ingest_min_gb:
        msg = f"SKIP — only {free_gb:.1f} GB free, need {ingest_min_gb:.0f} GB"
        logger.warning(msg)
        _notify_toast("sdet-brain daily SKIPPED", msg, ok=False)
        return 0

    # --- AC power / GPU busy guard ---
    if respect_idle:
        if not _ac_powered():
            logger.warning("SKIP — on battery power")
            _notify_toast("sdet-brain daily SKIPPED", "on battery power", ok=False)
            return 0
        if _gpu_busy():
            logger.warning("SKIP — GPU >50%% utilised (gaming? rendering?)")
            _notify_toast("sdet-brain daily SKIPPED", "GPU busy", ok=False)
            return 0

    # --- Server / Qdrant reachable? ---
    if not _server_reachable(server_url):
        msg = f"FAIL — sdet-brain server unreachable at {server_url}"
        logger.error(msg)
        _notify_toast("sdet-brain daily FAIL", msg, ok=False)
        return 1
    if not _qdrant_reachable(qdrant_url):
        msg = f"FAIL — Qdrant unreachable at {qdrant_url}"
        logger.error(msg)
        _notify_toast("sdet-brain daily FAIL", msg, ok=False)
        return 1

    # --- Ingest ---
    paths = _collect_paths()
    if not paths:
        logger.warning(
            "no corpus paths configured (set DRAFTS_PATHS / ARTICLES_PATHS / "
            "PROJECT_KNOWLEDGE_PATHS / CORPUS_PATHS env)"
        )
        _notify_toast("sdet-brain daily", "no corpus paths configured", ok=False)
        return 0

    total_chunks = 0
    failures = 0
    for path in paths:
        ok, chunks = _post_ingest(server_url, path, logger)
        total_chunks += chunks
        if not ok:
            failures += 1

    # --- Snapshot (optional) ---
    if snapshot_enabled and failures == 0:
        _snapshot_qdrant(qdrant_url, collection, logger)

    # --- Disk space sanity ---
    state_path = _state_dir()
    free_disk = _disk_free_gb(state_path)
    if free_disk < 5:
        logger.warning("low disk: %.1f GB free at %s", free_disk, state_path)

    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary = f"chunks={total_chunks} failures={failures} duration={finished}"
    if failures == 0:
        logger.info("=== daily OK %s ===", summary)
        _notify_toast("sdet-brain daily OK", f"{total_chunks} chunks", ok=True)
        return 0
    logger.error("=== daily FAIL %s ===", summary)
    _notify_toast("sdet-brain daily FAIL", f"{failures} path(s) failed", ok=False)
    return 1


if __name__ == "__main__":
    sys.exit(main())
