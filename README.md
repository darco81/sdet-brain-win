# sdet-brain-win

> **Windows + CUDA fork of [`darco81/sdet-brain`](https://github.com/darco81/sdet-brain).**
> Same persistent-RAG core as the Mac flagship, stripped of MLX and the
> local LLM router for a **4 GB VRAM** budget. Uses **Ollama** for
> embeddings (bge-m3) and **fastembed** ONNX for reranker + sparse.
> See [`NOTICE.md`](NOTICE.md) for the fork relationship and
> [docs/upstream-sync.md](docs/upstream-sync.md) for the sync workflow.

[![Version](https://img.shields.io/badge/version-0.1.0--win.0-blue.svg)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org)
[![License](https://img.shields.io/badge/license-Source--Available-yellow.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-pre--alpha-orange.svg)](#status)

## Reference hardware

Designed to run on a budget gaming PC. Tested baseline:

| Component | Spec |
|---|---|
| OS | Windows 11 |
| GPU | NVIDIA RTX 3050 / 3050 Ti **4 GB VRAM** |
| CPU | Intel i5 11th gen / AMD Ryzen X3D (96 MB L3) |
| RAM | 32 GB |

Both 12 GB VRAM and 16 GB VRAM machines are happily supported too —
4 GB is just the floor the codebase was tuned for.

## Status

**Live-verified on 2026-05-14** — Intel i5 11th gen / 32 GB RAM / RTX 3050 Ti 4 GB VRAM / Windows 11. End-to-end pipeline (ingest → embed → store → search → daily automation → snapshots) passes on the reference target hardware. See [CHANGELOG.md](CHANGELOG.md) `0.1.0-win.1` for the full verification list.

## Onboarding — full walkthrough

Greenfield install on a fresh Windows machine takes ~30 min including downloads. Half of that is `ollama pull bge-m3` and `uv sync` running unattended.

### Step 0 — Prerequisites

Need installed on your Windows 11 machine before cloning:

| Tool | One-line install (PowerShell as Admin) |
|------|----------------------------------------|
| Git for Windows | `winget install --id Git.Git --silent` |
| GitHub CLI | `winget install --id GitHub.cli --silent` |
| Docker Desktop | `winget install --id Docker.DockerDesktop --silent` → **reboot** + start the app once |
| Ollama for Windows | download `.exe` from https://ollama.com/download/windows → run installer |
| uv (Python project manager) | `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |

After install: `gh auth login` to give the GitHub CLI a token for cloning.

### Step 1 — Clone the fork

```powershell
mkdir C:\Users\<USER>\dev -Force
cd C:\Users\<USER>\dev
git clone git@github.com:darco81/sdet-brain-win.git
cd sdet-brain-win
git checkout windows-port
```

Or via HTTPS if SSH not set up:

```powershell
git clone https://github.com/darco81/sdet-brain-win.git
```

### Step 2 — Verify the environment with bootstrap.ps1

```powershell
.\scripts\bootstrap.ps1
```

Output is human-readable, each missing piece prints its install command. Expect:

```
[ OK ] Docker daemon reachable
[ OK ] Ollama CLI installed
[ OK ] Ollama service reachable on localhost:11434
[ OK ] uv installed
[ OK ] git installed
[ OK ] gh CLI installed
[ OK ] nvidia-smi reachable
    NVIDIA GeForce RTX 3050 Ti Laptop GPU, 4096 MiB, 591.74
[ OK ] VRAM 4 GB >= required 4 GB
[ OK ] Total RAM ~32 GB, free ~20 GB
```

If the summary line says `bge-m3 not pulled`, that's expected — fix it in step 3.

### Step 3 — Pull the embedding model

```powershell
ollama pull bge-m3        # ~1.2 GB download, ~3-5 min
ollama list               # verify: bge-m3:latest 1.2 GB
```

bge-m3 is a multilingual (PL + EN + 100+ languages) bi-encoder. In Q4 GGUF on Ollama it uses ~440 MB VRAM at inference time.

### Step 4 — Start Qdrant

```powershell
docker compose -f docker\docker-compose.yml up -d
```

Verify:

```powershell
(Invoke-WebRequest http://localhost:6333/readyz -UseBasicParsing).Content
# expected: "all shards are ready"
```

### Step 5 — Install Python deps + pre-warm the reranker

```powershell
uv sync --extra dev
uv run python scripts\warmup.py     # ~500 MB ONNX download, cached for life
```

`warmup.py` pulls the cross-encoder reranker (jina-reranker-v2-base-multilingual ONNX, runs on CPU via fastembed) and probes Ollama. Run once per machine — first MCP / search call without warmup adds 30-60 s of one-time download which can time out Claude Desktop's stdio handshake.

### Step 6 — Configure your corpus

```powershell
copy .env.example .env
notepad .env
```

Edit at minimum:

```env
# Semicolon-separated (Windows convention)
DRAFTS_PATHS=C:\Users\<USER>\dev\my-brand-drafts
PROJECT_KNOWLEDGE_PATHS=C:\Users\<USER>\dev\my-projects
```

Paths can be empty for a smoke test — pass the path on the `POST /ingest` body instead.

### Step 7 — Start the server

```powershell
uv run sdet-brain-server
```

The server auto-creates the Qdrant collection on startup (idempotent, with retry/backoff to survive Qdrant container cold-start race).

Verify in a second PowerShell:

```powershell
Invoke-RestMethod http://localhost:8080/health | ConvertTo-Json
```

Expected:

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

### Step 8 — Smoke ingest + search

```powershell
# Make a test corpus (or point at your real Markdown tree)
mkdir C:\Users\<USER>\dev\test-corpus -Force
"# Hello world`n`nTest markdown for embedding." | Out-File C:\Users\<USER>\dev\test-corpus\hello.md -Encoding UTF8

# Ingest
$body = @{ path="C:\Users\<USER>\dev\test-corpus"; force=$true } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8080/ingest -Method POST -Body $body -ContentType "application/json"
# expect: chunks_created > 0

# Search
$body = @{ query="hello"; limit=2 } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8080/search -Method POST -Body $body -ContentType "application/json"
# expect: results array with score
```

**Performance benchmark on RTX 3050 Ti reference hardware:** 1042 chunks ingested from 6 markdown files (724 KB LinkedIn export) in **35.4 s ≈ 29 chunks/sec**.

### Step 9 — Wire to Claude Code CLI

If you use `claude` (Claude Code CLI), add the MCP entry to `~/.claude.json` via merge — DO NOT overwrite the file (it contains your sessions cache). Easiest:

```powershell
# Drop merge script
python -c "
import json, pathlib
p = pathlib.Path.home() / '.claude.json'
cfg = json.loads(p.read_text(encoding='utf-8'))
cfg.setdefault('mcpServers', {})['sdet-brain'] = {
  'command': r'C:\Users\<USER>\.local\bin\uv.exe',
  'args': ['run', '--directory', r'C:\Users\<USER>\dev\sdet-brain-win', 'sdet-brain-mcp-stdio'],
  'env': {
    'EMBEDDING_PROVIDER': 'ollama',
    'OLLAMA_HOST': 'http://localhost:11434',
    'OLLAMA_EMBED_MODEL': 'bge-m3',
    'QDRANT_URL': 'http://localhost:6333',
    'RERANK_ENABLED': 'true',
  },
}
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding='utf-8')
print('OK')
"
```

Restart Claude Code (close all `claude` processes, open new terminal). Type `/mcp` in a Claude Code chat — `sdet-brain` should appear with all tools.

### Step 10 — Wire to Claude Desktop

**Limitation:** Claude Desktop MSIX (Microsoft Store version, Anthropic's current Windows distribution) does **not** currently load `claude_desktop_config.json` for local MCP servers. Tracking upstream for Store support.

If you have the **classic standalone .exe** version of Claude Desktop, copy `examples\claude-desktop-mcp.json` to `%APPDATA%\Claude\claude_desktop_config.json` (substitute `<USER>`), tray Quit + reopen the app. The `search` tool should appear under the hammer icon in chat.

### Step 11 — (Optional) Daily automation

```powershell
schtasks /Create /XML scripts\windows-task-scheduler.xml /TN sdet-brain-daily
schtasks /Run /TN sdet-brain-daily   # test manual fire right now
```

`daily.py` runs Mon-Fri at 07:30 local time, only on AC power, only when at least 8 GB RAM free. It reuses the running server's HTTP `/ingest` endpoint (no second MLX/embedder process), takes a Qdrant snapshot to `.qdrant_backups/` (keep last 7), and emits a Windows toast notification on completion.

Manual fire (any time):

```powershell
uv run python scripts\daily.py
```

---

Detailed setup walkthrough: [docs/windows-setup.md](docs/windows-setup.md).
Troubleshooting common issues: [docs/troubleshooting.md](docs/troubleshooting.md).
Sync from upstream `darco81/sdet-brain`: [docs/upstream-sync.md](docs/upstream-sync.md).

## What was stripped from upstream

| File / module | Why removed |
|---|---|
| `src/sdet_brain/embeddings/mlx_provider.py` | Apple Silicon / Metal only |
| `src/sdet_brain/llm/` (whole dir) | Qwen3-Next-80B needs 40+ GB, doesn't fit |
| `src/sdet_brain/server/tools/{query_rewrite,multi_query,summarize_results}.py` | Depended on local LLM |
| `src/sdet_brain/server/chat/`, `routes/chat.py`, `cli/chat_repl.py` | LLM REPL surface |
| `scripts/daily.sh`, `scripts/healthcheck.sh`, `scripts/digest.py` | bash + macOS-specific |
| `mlx-embeddings`, `mlx-lm` deps | obvious |

## What was added or replaced

| Path | Purpose |
|---|---|
| `src/sdet_brain/embeddings/ollama_provider.py` | New `OllamaEmbedder` — HTTP wrapper for `ollama serve`. ~150 LOC with batching, dim probing, dim-drift detection, context manager. |
| `scripts/daily.py` | Cross-OS daily reingest (psutil + httpx). Memory guard, AC-power guard, GPU-busy guard, Qdrant snapshot, toast notifications. |
| `scripts/windows-task-scheduler.xml` | Importable Task Scheduler config (Mon-Fri 07:30, weekday-only, AC-only). |
| `scripts/bootstrap.ps1` | One-shot dependency check + install instructions for missing pieces. |
| `examples/claude-desktop-mcp.json` | Drop-in template for `%APPDATA%\Claude\claude_desktop_config.json`. |
| `examples/claude-code-mcp.json` | Drop-in template for `%USERPROFILE%\.claude\mcp_servers.json`. |
| `docs/windows-setup.md` | Step-by-step setup. |
| `docs/troubleshooting.md` | Common Windows-specific failure modes + fixes. |
| `docs/upstream-sync.md` | How to pull bug fixes from upstream without losing the strip. |

## What stayed identical to upstream

* `src/sdet_brain/embeddings/reranker.py` — fastembed cross-platform.
* `src/sdet_brain/embeddings/sparse_embedder.py` — fastembed BM25.
* `src/sdet_brain/embeddings/gemini_provider.py` — cloud fallback.
* `src/sdet_brain/server/*` — FastAPI + FastMCP.
* `src/sdet_brain/storage/*` — Qdrant client.
* `src/sdet_brain/ingestion/*` — chunker, classifier, pipeline.
* Qdrant container config + bind-mount layout.

## One nice fix backported value-add

The server now auto-creates the Qdrant collection on startup
(`init_collections` invoked from the FastAPI lifespan, idempotent).
Upstream historically only ran this from the CLI — dropping a
collection used to require a manual one-liner before the server
could be useful again. **Not in this fork.** ([app.py lifespan](src/sdet_brain/server/app.py))

## Architecture in one picture

```
┌─────────────────┐     stdio MCP    ┌──────────────────────┐
│ Claude Desktop  ├─────────────────►│                      │
└─────────────────┘                  │                      │
                                     │  sdet-brain-server   │     HTTP
┌─────────────────┐     stdio MCP    │  (FastAPI + FastMCP) ├──────────┐
│ Claude Code     ├─────────────────►│  ~150 MB RSS         │          │
└─────────────────┘                  │                      │          │
                                     └──────────┬───────────┘          │
                                                │                       ▼
                  ┌─────────────────────────────┼────────────────┐ ┌─────────────┐
                  │                             │                │ │             │
                  ▼                             ▼                ▼ │   Ollama    │
            ┌──────────┐              ┌─────────────────┐         │  bge-m3 GPU │
            │  Qdrant  │              │   fastembed     │         │  ~440MB VRAM│
            │  Docker  │              │  reranker+BM25  │         │             │
            │ ~300MB   │              │   CPU-only      │         └─────────────┘
            └──────────┘              └─────────────────┘
```

Total resident memory ≈ ~1.5 GB RAM + ~440 MB VRAM at idle (after first embed call).


## MCP tools available

| Tool | Purpose |
|---|---|
| `search` | Hybrid (dense + BM25) retrieval with optional reranker. The bread and butter. |
| `multi_query_search` | _(stripped — depended on local LLM router)_ |
| `query_rewrite` | _(stripped — depended on local LLM router)_ |
| `summarize_results` | _(stripped — depended on local LLM router)_ |
| `get_chunk_neighbors` | Pull the chunk(s) adjacent to a hit when you need surrounding context. |
| `list_sources` | Inspect what's indexed by source_type. |
| `list_articles_by_status`, `search_voice_samples`, `search_smaczki`, `search_decisions`, `search_sprint_reports` | Domain-specific helpers (search with payload filters baked in). |

7 tools total. The 3 LLM-bound ones were removed because Qwen3-Next-80B
won't fit a 4 GB VRAM target. If you want decomposition or summarisation,
do it client-side in Claude Desktop / Code (their host LLM handles it).

## Documentation

* **[docs/windows-setup.md](docs/windows-setup.md)** — full step-by-step walkthrough, prerequisites through MCP wiring.
* **[docs/troubleshooting.md](docs/troubleshooting.md)** — 11 common Windows-specific failures + copy-paste fixes.
* **[docs/upstream-sync.md](docs/upstream-sync.md)** — how to pull bug fixes from `darco81/sdet-brain` without losing the strip.
* **[NOTICE.md](NOTICE.md)** — fork relationship, license attribution.
* **[CHANGELOG.md](CHANGELOG.md)** — version history starting from `0.1.0-win.0`.

## Status

**Pre-alpha.** Code committed and unit-tested on macOS. First live
Windows verification happens on an i5 11gen / 32 GB RAM / RTX 3050 Ti
4 GB box. Expect a handful of fixup commits after that test run.

ClickUp implementation plan: `SDET Brand → SDET Brain Win` folder
(private). 61 subtasks across phases P0–P6 with dependencies.

## License

[Source-Available](LICENSE) (TBD), Copyright (c) 2026 Dariusz Kowalski.
Same terms as upstream — see [`NOTICE.md`](NOTICE.md).
