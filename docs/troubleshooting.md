# Troubleshooting

Common Windows-specific issues and fixes. Run `scripts\bootstrap.ps1`
first — it catches the most frequent ones.

## Ollama: port 11434 already in use

Another process (or a previous Ollama instance) is bound.

```powershell
# find the PID
Get-NetTCPConnection -LocalPort 11434 | Select-Object OwningProcess
Get-Process -Id <PID>
# kill if it's a stale Ollama
Stop-Process -Id <PID>
# restart
ollama serve
```

## Docker Desktop won't start

* Ensure **WSL 2** is enabled: `wsl --install` then reboot.
* Check virtualization is enabled in BIOS.
* If Hyper-V conflicts with VirtualBox/VMware: open *Turn Windows
  features on or off* and decide which hypervisor wins. Docker
  Desktop uses WSL2 backend by default, which coexists with VMware
  16.2+ but breaks older versions.

## nvidia-smi: GPU not detected

* Driver too old: update via NVIDIA app or GeForce Experience to
  ≥ 535.x (CUDA 12.x compatible).
* In Device Manager check the GPU is enabled.
* Resizable BAR: usually fine, but if you have a hybrid Optimus
  laptop, force the dGPU for Ollama: NVIDIA Control Panel → 3D
  Settings → Add `ollama.exe` → Use High-performance NVIDIA
  processor.

## fastembed: DLL load failed

ONNX runtime wheels sometimes need Visual C++ runtime libs.

```powershell
# Install Visual Studio Build Tools (minimal "Desktop development with C++")
winget install --id Microsoft.VisualStudio.2022.BuildTools
```

If still failing, force a CPU-only build of fastembed:

```powershell
uv pip install --reinstall fastembed-onnxruntime
```

## Qdrant: collection volume permissions

If Qdrant logs `permission denied` on `/qdrant/storage`:

```powershell
# in PowerShell as admin
icacls "docker\qdrant_storage" /grant Everyone:F /T
```

Restart the container: `docker compose restart qdrant`.

## MCP server doesn't appear in Claude Code/Desktop

* Did you fully **quit** Claude Desktop (not just close window)?
  Use Tray icon → Quit.
* Path in config uses **double backslashes** in JSON: `C:\\Users\\…`.
* Try `uv run sdet-brain-server` manually first — if it crashes
  in your terminal, the MCP client can't recover.
* Check the path under `command`: must be `uv.exe` (or full path
  `C:\\Users\\<USER>\\.local\\bin\\uv.exe`) if `uv` is not on the
  PATH visible to Claude Desktop. Claude Desktop **does not** load
  your shell rc files.

## Claude Desktop returns garbled snippets / mojibake / "głupoty"

Snippets quoted from the brain show `?` `�` `�?"` where em-dashes,
Polish letters, or smart quotes should be — and the model
hallucinates from the corrupted input.

**Cause**: Python on Windows defaults `stdout` to **cp1252**. The
MCP server emits JSON-RPC with `ensure_ascii=False`; non-ASCII bytes
turn into mojibake before reaching Claude Desktop.

**Fix** (`0.1.0-win.2` and later already include the code fix):
1. `git pull origin windows-port` — version ≥ `0.1.0-win.2`.
2. Add to your MCP config `env` block:
   ```json
   "PYTHONIOENCODING": "utf-8",
   "PYTHONUTF8": "1"
   ```
3. Tray-Quit + reopen Claude Desktop.

**Verify** (don't trust `Invoke-RestMethod` — it has a PS5.1 codepage
bug; use `Invoke-WebRequest -OutFile` to inspect raw bytes):

```powershell
$body = @{limit=1; with_payload=$true} | ConvertTo-Json
Invoke-WebRequest -Uri "http://localhost:6333/collections/sdet_brand_v1/points/scroll" `
    -Method POST -ContentType "application/json" -Body $body -OutFile "$env:TEMP\q.bin"
$bytes = [System.IO.File]::ReadAllBytes("$env:TEMP\q.bin")
# em-dash UTF-8 sequence is E2 80 94 — count occurrences:
$count = 0
for ($i=0; $i -lt $bytes.Length-2; $i++) {
    if ($bytes[$i] -eq 0xE2 -and $bytes[$i+1] -eq 0x80 -and $bytes[$i+2] -eq 0x94) { $count++ }
}
"Em-dashes in Qdrant raw: $count"
```

If Qdrant raw has em-dashes (>0) but Claude Desktop still mangles
them, the MCP server itself is downgrading at stdio — confirm
`PYTHONIOENCODING=utf-8` is in your config env block.

## "Could not attach to MCP server sdet-brain" after a code update

`uv run` rebuilds and reinstalls the editable wheel on the first
spawn after any source change. A long-running `sdet-brain-server`
(HTTP) process holds `.venv\Scripts\sdet-brain-server.exe` open,
which makes the reinstall fail with `os error 32 — file in use`,
and Claude Desktop's spawn dies before MCP handshake.

```powershell
.\scripts\update.ps1 -Force    # stops the HTTP server, then git pull + uv sync
```

Or manually: stop the HTTP server (Ctrl+C in its PowerShell window),
let `uv sync` complete, then restart Claude Desktop.

## PowerShell 5.1 `Invoke-RestMethod` corrupts UTF-8 when debugging

When you pipe a JSON response through `Invoke-RestMethod | ConvertTo-Json`
in PowerShell 5.1, em-dashes and Polish diacritics get re-encoded into
mojibake **inside PowerShell**, not on the wire. This will lead you to
falsely diagnose your server / Qdrant as broken.

Always use `Invoke-WebRequest -OutFile` + `[System.IO.File]::ReadAllBytes()`
to capture and inspect raw server bytes when debugging encoding.

## daily.py: permission denied writing log

`%LOCALAPPDATA%\sdet-brain\daily.log` directory will be created on
first run. If it isn't, create it manually or set `DAILY_LOG=...`
in `.env` to a path you can write.

## Toast notifications not showing

* Notification settings → make sure focus assist isn't blocking
  apps in "Off" mode.
* Make sure `windows-toasts` is installed: `uv pip list | findstr toast`.
  If missing, run `uv sync` again.
* On first toast Windows may ask you to enable notifications for
  the host process — allow it.

## Ingest runs out of VRAM

bge-m3 in Q4 needs ~440 MB; if any other process holds the GPU
(games, video editors, OBS), Ollama may evict your model between
calls and re-load each time. Workarounds:

* Close GPU-heavy apps before ingest.
* Set `OLLAMA_KEEP_ALIVE=24h` (or longer) before running `ollama serve`.
* Reduce `OLLAMA_BATCH_SIZE` in `.env` to 8 or 4 to keep peak VRAM
  lower.

## Server health stays `degraded` after restart

Check `/health` response:

```powershell
curl http://localhost:8080/health
```

* `qdrant_ok: false` → docker not running, or `QDRANT_URL` wrong.
* `embedder_ok: false` + `embedder_provider: ollama` → Ollama not
  running or model not pulled.
* `collection_count: null` and `qdrant_error: ... doesn't exist` →
  rare in this fork (startup hook auto-creates the collection). If
  it happens, run the manual init from `docs/windows-setup.md` Step 5
  fallback.

## "ImportError: No module named sdet_brain" when running pytest

You ran `pytest` outside of the uv venv. Use:

```powershell
uv run pytest
```

Always. The bare `pytest` picks up your system Python which doesn't
know about this project.
