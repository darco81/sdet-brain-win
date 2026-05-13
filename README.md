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

## Quick start (15 minutes)

```powershell
# 1. Clone + verify environment
git clone git@github.com:darco81/sdet-brain-win.git
cd sdet-brain-win
.\scripts\bootstrap.ps1

# 2. Pull embedding model
ollama pull bge-m3

# 3. Start Qdrant
docker compose -f docker\docker-compose.yml up -d

# 4. Install Python deps + warm up the reranker cache
uv sync --extra dev
uv run python scripts\warmup.py    # one-time, ~500 MB ONNX download
copy .env.example .env             # then edit corpus paths

# 5. Start the server
uv run sdet-brain-server
```

Detailed walkthrough: [docs/windows-setup.md](docs/windows-setup.md).
If something doesn't work: [docs/troubleshooting.md](docs/troubleshooting.md).

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
