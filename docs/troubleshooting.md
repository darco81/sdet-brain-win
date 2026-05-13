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
