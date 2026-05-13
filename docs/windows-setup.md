# Windows setup — step by step

Target hardware: anything with a modest NVIDIA GPU. Tested baseline:
**Intel i5 11th gen, 32 GB RAM, RTX 3050 Ti 4 GB VRAM, Windows 11**.

## 0. Prerequisites overview

| Tool | What for | Install |
|------|----------|---------|
| Docker Desktop | Qdrant container | https://www.docker.com/products/docker-desktop |
| Ollama | bge-m3 embeddings on CUDA | https://ollama.com/download/windows |
| NVIDIA driver ≥ 535 | CUDA 12.x for Ollama | NVIDIA app or GeForce Experience |
| Python 3.12 | Project runtime | Optional — uv installs one |
| uv | Python project manager | `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| Git | Source control | `winget install --id Git.Git` |
| gh CLI | GitHub interactions (optional) | `winget install --id GitHub.cli` |

After installing, run the included `scripts\bootstrap.ps1` for a guided check:

```powershell
cd C:\Users\<USER>\dev\sdet-brain-win
.\scripts\bootstrap.ps1
```

Each missing piece prints its install command.

## 1. Pull the embedding model

```powershell
ollama pull bge-m3
ollama list
```

Expect ~2 GB on disk, ~440 MB VRAM at inference. If `nvidia-smi`
shows the `ollama` process during embed calls, GPU acceleration is on.

## 2. Start Qdrant

```powershell
cd C:\Users\<USER>\dev\sdet-brain-win
docker compose -f docker\docker-compose.yml up -d
curl http://localhost:6333/readyz
```

Expect `all shards are ready`.

> If Docker Desktop eats too much RAM, cap it in
> *Settings → Resources → Memory* (4-6 GB is plenty for Qdrant alone).

## 3. Set up the Python env

```powershell
cd C:\Users\<USER>\dev\sdet-brain-win
uv sync --extra dev
```

This creates `.venv\` and installs everything from `pyproject.toml`.

## 4. Configure the corpus paths

Copy `.env.example` to `.env` and edit the path variables. On Windows
use **semicolon `;`** as the separator:

```env
EMBEDDING_PROVIDER=ollama
OLLAMA_EMBED_MODEL=bge-m3
QDRANT_URL=http://localhost:6333
RERANK_ENABLED=true

DRAFTS_PATHS=C:\Users\<USER>\dev\my-brand-drafts
PROJECT_KNOWLEDGE_PATHS=C:\Users\<USER>\dev\my-projects
```

## 5. Start the server

```powershell
uv run sdet-brain-server
```

The server auto-creates the Qdrant collection on first start (no
manual `init_collections` workaround required — that bug is fixed in
this fork). Hit `http://localhost:8080/health` to confirm:

```json
{
  "status": "ok",
  "qdrant_ok": true,
  "embedder_ok": true,
  "embedder_provider": "ollama",
  "vector_size": 1024,
  "collection_count": 0
}
```

## 6. Ingest your corpus

```powershell
curl -X POST http://localhost:8080/ingest `
  -H "Content-Type: application/json" `
  -d '{\"path\":\"C:\\Users\\<USER>\\dev\\my-brand-drafts\",\"force\":true}'
```

A small corpus (~10 markdown files) should finish in seconds. A full
brand corpus (~5000 chunks) usually takes 2-4 minutes on RTX 3050 Ti.

## 7. Wire it to Claude Desktop or Claude Code

Copy `examples\claude-desktop-mcp.json` into
`%APPDATA%\Claude\claude_desktop_config.json` (replace placeholders),
fully quit and reopen Claude Desktop. The `search` tool should
appear in chat.

For Claude Code CLI: copy `examples\claude-code-mcp.json` into
`%USERPROFILE%\.claude\mcp_servers.json` and restart Claude Code.

## 8. (Optional) Daily automation

```powershell
schtasks /Create /XML scripts\windows-task-scheduler.xml /TN sdet-brain-daily
schtasks /Run /TN sdet-brain-daily   # test manual fire
```

`scripts\daily.py` reads `INGEST_MIN_GB` (default 8), `CORPUS_PATHS`
or per-source `DRAFTS_PATHS` etc., hits the running server via HTTP,
and toasts Windows Notification Center on success/fail.

If you don't want the scheduled task, just run it manually whenever
your corpus changes:

```powershell
uv run python scripts\daily.py
```

## Common follow-ups

* [Troubleshooting](troubleshooting.md) — Ollama port conflicts, fastembed wheel issues, Docker WSL2 setup.
* [Upstream sync](upstream-sync.md) — how to pull bug fixes from `darco81/sdet-brain` without losing the Windows port.
