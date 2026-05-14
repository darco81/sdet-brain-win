# sdet-brain-win

> **Windows + CUDA fork of [`darco81/sdet-brain`](https://github.com/darco81/sdet-brain).**
> Same persistent-RAG core as the Mac flagship, stripped of MLX and the
> local LLM router for a **4 GB VRAM** budget. Uses **Ollama** for
> embeddings (bge-m3) and **fastembed** ONNX for reranker + sparse.
> See [`NOTICE.md`](NOTICE.md) for the fork relationship and
> [docs/upstream-sync.md](docs/upstream-sync.md) for the sync workflow.

[![Version](https://img.shields.io/badge/version-0.1.0--win.2-blue.svg)](CHANGELOG.md)
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

**Live-verified on 2026-05-14 (`0.1.0-win.2`)** — Intel i5 11th gen / 32 GB RAM / RTX 3050 Ti 4 GB VRAM / Windows 11. End-to-end pipeline (ingest → embed → store → search → daily automation → snapshots) passes on the reference target hardware. `0.1.0-win.2` ships a **critical UTF-8 stdio fix for the MCP server** — without it Claude Desktop on Windows shows garbled snippets (mojibake) for any content containing em-dashes, Polish diacritics, or smart quotes. macOS users are unaffected. See [CHANGELOG.md](CHANGELOG.md) for the full verification list.

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
    'PYTHONIOENCODING': 'utf-8',
    'PYTHONUTF8': '1',
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

> Alternative path: create `%USERPROFILE%\.claude\mcp_servers.json` directly from `examples\claude-code-mcp.json` (substitute `<USER>` first). Both layouts are read by Claude Code; pick whichever matches your existing setup.

### Step 10 — Wire to Claude Desktop (Windows MSIX)

**It works after this exact dance** — verified on Claude Desktop `1.7196.0.0` (Windows MSIX from Microsoft Store / claude.ai/download). Plus a few gotchas worth knowing:

**The actual file Claude Desktop reads on Win MSIX:**

```
C:\Users\<USER>\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json
```

This is the **UWP-virtualised** version of `%APPDATA%\Claude\claude_desktop_config.json`. Both paths point at the same file thanks to MSIX's redirect, so you can edit either — but the canonical one is the long UWP path. Confirm by opening Claude Desktop → **Settings → Developer → Edit Config** — Notepad opens the file Claude Desktop is actually reading.

**Drop merge (PowerShell, preserves existing `preferences` if Claude already created the file):**

> **The `PYTHONIOENCODING` / `PYTHONUTF8` env vars below are mandatory on Windows.** Without them Claude Desktop will receive corrupted snippet text (em-dashes, Polish diacritics, smart quotes turning into `?` or `�`) and the model will hallucinate nonsense from the garbage. `0.1.0-win.2`'s `mcp_stdio.py` already calls `sys.stdout.reconfigure(encoding="utf-8")` at start, but keeping these env vars in the config is belt-and-suspenders + survives any future regression.

```powershell
# Save script to temp, run, cleanup
@'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
cfg = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
cfg.setdefault('mcpServers', {})['sdet-brain'] = {
    'command': r'C:\Users\<USER>\.local\bin\uv.exe',
    'args': ['run', '--directory', r'C:\Users\<USER>\dev\sdet-brain-win', 'sdet-brain-mcp-stdio'],
    'env': {
        'PYTHONIOENCODING': 'utf-8',
        'PYTHONUTF8': '1',
        'EMBEDDING_PROVIDER': 'ollama',
        'OLLAMA_HOST': 'http://localhost:11434',
        'OLLAMA_EMBED_MODEL': 'bge-m3',
        'QDRANT_URL': 'http://localhost:6333',
        'RERANK_ENABLED': 'true',
    },
}
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding='utf-8')
print('OK')
'@ | Set-Content "$env:TEMP\merge-mcp.py" -Encoding UTF8

python "$env:TEMP\merge-mcp.py" "C:\Users\<USER>\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json"
```

**Then FULL restart Claude Desktop:**

1. **Tray icon** (bottom-right, near the clock) → right-click → **Quit** (NOT "close window" — close just hides; all 9 Claude processes keep running and the config never reloads)
2. Wait 5 seconds — verify with `Get-Process claude` (should return nothing)
3. Open Claude Desktop again from Start Menu
4. In a new chat, click the **hammer/tools icon** at the bottom-right of the input box → you should see `sdet-brain` with the list of tools (search, list_sources, get_chunk_neighbors, etc.)

**Critical Windows-specific gotchas:**

- ⚠️ **After every Claude Desktop reinstall**, the MSIX overwrites `claude_desktop_config.json` and wipes the `mcpServers` key from your config. You need to **re-merge** the MCP block. This repo's `examples\claude-desktop-mcp.json` is a clean template you can use as the source of truth.
- ⚠️ **`uv.exe` must be referenced by full absolute path** in the config — `C:\Users\<USER>\.local\bin\uv.exe` — not just `uv.exe`. Claude Desktop's spawned child process doesn't inherit the user's `PATH`.
- ⚠️ **Settings → Developer → Edit Config** opens the right file but **doesn't auto-reload** — you still need the tray-Quit + reopen step for changes to apply.
- ⚠️ **`EBUSY` errors in `main.log`** are usually NOT about your MCP server. They're Claude Desktop's bundled Claude Code Daemon (CCD) downloading + spawning its own `claude.exe`. Look for `MCP Server connection requested for: sdet-brain` lines — that's the actual MCP attempt. If you don't see them, the config wasn't picked up (= reinstall wipe, see above).
- ⚠️ **Anthropic also reads `~/.claude.json`** (the Claude Code CLI config) for some MCP-aware features. The included merge scripts populate both for safety.

**Claude Code CLI** is simpler — `~/.claude.json` MCP entry survives across versions, no UWP redirect issue. If Claude Desktop refuses to cooperate after a future Anthropic build change, Claude Code CLI always works.

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

## Verify your install (90-second smoke)

After Step 7 (server running on `:8080`):

```powershell
# 1) Health check — must all be true / non-empty
Invoke-RestMethod http://localhost:8080/health | ConvertTo-Json
# expected: status=ok, embedder_ok=True, qdrant_ok=True, vector_size=1024

# 2) Ingest a polish + em-dash test file
"# Polski test`n`nDziałanie em-dashem: ąęć — żźń." | Out-File `
    C:\Users\<USER>\dev\test-corpus\encoding-smoke.md -Encoding UTF8
$body = @{ path="C:\Users\<USER>\dev\test-corpus"; force=$true } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8080/ingest -Method POST `
    -Body $body -ContentType "application/json"

# 3) DIRECT Qdrant scroll — bypass our server to confirm bytes survived ingest
$body = @{limit=1; with_payload=$true} | ConvertTo-Json
Invoke-WebRequest -Uri "http://localhost:6333/collections/sdet_brand_v1/points/scroll" `
    -Method POST -ContentType "application/json" -Body $body `
    -OutFile $env:TEMP\qdrant_raw.bin
$bytes = [System.IO.File]::ReadAllBytes("$env:TEMP\qdrant_raw.bin")
$emDash = 0
for ($i = 0; $i -lt $bytes.Length - 2; $i++) {
    if ($bytes[$i] -eq 0xE2 -and $bytes[$i+1] -eq 0x80 -and $bytes[$i+2] -eq 0x94) {
        $emDash++
    }
}
"Em-dashes found in Qdrant raw bytes: $emDash  (must be > 0)"
```

If em-dashes ARE found in step 3, the data is clean. If Claude Desktop **still** shows garbled snippets after that, the MCP stdio layer is the culprit — confirm your config has `PYTHONIOENCODING=utf-8` in the `env` block + `0.1.0-win.2` code (`mcp_stdio.py` contains `_force_utf8_streams()`).

> **Don't** use `Invoke-RestMethod` to inspect server JSON when debugging encoding. PowerShell 5.1 has a known UTF-8 round-trip bug in `Invoke-RestMethod` → object → `ConvertTo-Json` that *itself* corrupts bytes. Always use `Invoke-WebRequest -OutFile` + `[System.IO.File]::ReadAllBytes()` for ground-truth byte inspection.

## Troubleshooting

### "Claude Desktop returns nonsense / głupoty when I search the brain"

**Symptom**: Snippets come back with `?` or `�` where em-dashes / Polish letters should be, OR the model fabricates citations that don't match the corpus.

**Cause**: Python on Windows defaults `stdout` to **cp1252** (Windows-1252). The MCP server writes JSON-RPC with `ensure_ascii=False`, so any non-ASCII byte (em-dash `\xe2\x80\x94`, Polish `ą` `\xc4\x85`, smart quote, bullet) gets re-encoded by Windows into mojibake before reaching Claude Desktop. The model then "hallucinates" off corrupted input.

**Fix**:
1. Pull latest fork (`git pull origin windows-port`) — version ≥ `0.1.0-win.2` has `_force_utf8_streams()` in `mcp_stdio.py`.
2. Add to your MCP config `env` block:
   ```json
   "PYTHONIOENCODING": "utf-8",
   "PYTHONUTF8": "1"
   ```
3. Tray-Quit + reopen Claude Desktop (a window-close doesn't reload config).

Verify: re-run the [Verify your install](#verify-your-install-90-second-smoke) snippet above. If raw Qdrant has em-dashes but Claude Desktop still doesn't, the MCP-server config is missing the env vars.

### "Could not attach to MCP server sdet-brain" right after a code update

**Cause**: `uv run` rebuilds and **reinstalls** the editable wheel on the first spawn after any source change. If you have a long-running `sdet-brain-server` (HTTP) process holding `.venv\Scripts\sdet-brain-server.exe` open, the reinstall fails with `os error 32 — file in use`, and Claude Desktop's spawn dies before MCP handshake.

**Fix**:
```powershell
.\scripts\update.ps1 -Force    # stops the HTTP server, then runs git pull + uv sync
```
Or manually: stop the HTTP server (Ctrl+C in its PowerShell window), wait for `uv sync` to complete in any pending window, then restart Claude Desktop.

### "Claude Desktop's hammer icon doesn't show sdet-brain at all"

Check, in order:
1. **Right config path?** Open `Settings → Developer → Edit Config` — that's the file Claude Desktop reads. Confirm your `mcpServers.sdet-brain` block lives there. The Windows MSIX path is `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`, NOT `%APPDATA%\Claude\...`.
2. **Full restart?** Tray icon → right-click → Quit, then reopen. Window-close doesn't reload config.
3. **MCP log present?** Open `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\logs\mcp.log` and tail the last 30 lines. If you see `MCP Server connection requested for: sdet-brain`, the config was read. If not, the file is still wrong.
4. **`uv.exe` absolute path?** Claude Desktop spawns subprocesses without inheriting your `PATH`. Use the full `C:\Users\<USER>\.local\bin\uv.exe`, not just `uv` or `uv.exe`.
5. **Server attaches but immediately disconnects?** Tail `logs\mcp-server-sdet-brain.log`. The Python subprocess's stderr lands there — `pip` install failures, ImportError, port-bind conflicts, Ollama unreachable all show up. Usually one of: Ollama not running, Qdrant container not started, lingering `sdet-brain-server.exe` holding the venv lock (see previous gotcha).

### "I get `EBUSY` errors in `main.log`"

Those are Claude Desktop's bundled Claude Code Daemon (CCD) spawning its own `claude.exe`. They are NOT about your MCP server. Look for `MCP Server connection requested for: sdet-brain` instead.

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
