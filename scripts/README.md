# Windows scripts

Helper scripts for running `sdet-brain-win` on Windows. None are required
to use the brain — they make setup and the daily flow hands-off. (The
upstream macOS `daily.sh` / `digest.py` / `healthcheck.sh` + launchd
plist are **not** carried in this fork; this README documents the
Windows equivalents that actually ship here.)

## What you get

- **`bootstrap.ps1`** — environment doctor. Checks Docker Desktop,
  Ollama + the `bge-m3` model, `uv`, Git, `gh`, and the NVIDIA driver,
  printing actionable install hints for anything missing. Exit 0 = all
  green. `-RequiredVramGb` defaults to 4.
- **`daily.py`** — daily corpus reingest + health check (the `daily.sh`
  replacement). Pure Python, so it works under Task Scheduler, WSL,
  Linux cron, or a manual `python scripts/daily.py`. Skips the run when
  available RAM is below `INGEST_MIN_GB` (default 8). Routes ingest
  through the running server's `POST /ingest` (one Ollama instance, no
  duplicate model), and optionally snapshots the Qdrant collection when
  `QDRANT_SNAPSHOT_ENABLED=true`. Logs to `DAILY_LOG`
  (default `%LOCALAPPDATA%\sdet-brain\daily.log`).
- **`warmup.py`** — pre-downloads the fastembed reranker (~500 MB ONNX)
  and, optionally, `bge-m3` via Ollama, so the first MCP server boot
  doesn't stall the Claude Desktop stdio handshake on a cold download.
  Idempotent.
- **`update.ps1`** — `git pull` (windows-port) → `uv sync --extra dev`
  if `pyproject.toml` changed → stop the server so the next start picks
  up new code. `-SkipSync` / `-Force` available. Leaves the Qdrant
  container alone (its data is persistent).
- **`windows-task-scheduler.xml`** — Task Scheduler import that runs
  `uv run --directory <repo> python scripts\daily.py` on a daily 07:30
  trigger.
- **`examples/`** — `paths.env.example`, `discord.env.example`, and a
  launchd plist example (kept only as a reference for anyone mirroring
  the macOS setup; not used on Windows).

## First-time setup

```powershell
# 1. Verify the environment.
.\scripts\bootstrap.ps1

# 2. Install deps + warm the model caches (once, after uv sync).
uv sync --extra dev
uv run python scripts\warmup.py

# 3. Configure .env (corpus paths, OCR, daily.py knobs) — see .env.example
copy .env.example .env
notepad .env
```

## Daily automation (Task Scheduler)

```powershell
# Edit the <USER> placeholder in the XML to your repo path, then import:
schtasks /Create /TN "sdet-brain daily" /XML scripts\windows-task-scheduler.xml

# Run it now to smoke-test:
schtasks /Run /TN "sdet-brain daily"
```

`daily.py` configuration is via environment variables (read from `.env`):
`INGEST_MIN_GB`, `CORPUS_PATHS`, `SDET_BRAIN_SERVER_URL`,
`QDRANT_SNAPSHOT_ENABLED`, `RESPECT_USER_IDLE`, `DAILY_LOG`. See
[`.env.example`](../.env.example) for the full list and defaults.

## Updating

```powershell
.\scripts\update.ps1            # pull + sync + stop server
.\scripts\update.ps1 -SkipSync  # just git pull
```
