<#
.SYNOPSIS
  Verify the Windows environment is ready for sdet-brain-win.

.DESCRIPTION
  Checks Docker Desktop, Ollama, bge-m3 model, uv, Git, gh, NVIDIA driver.
  Each missing dependency prints actionable install instructions.
  Exit code 0 = all green, 1 = at least one missing.

.EXAMPLE
  PS> .\scripts\bootstrap.ps1
  PS> .\scripts\bootstrap.ps1 -Verbose
#>

[CmdletBinding()]
param(
  [int]$RequiredVramGb = 4
)

$ErrorActionPreference = 'Continue'  # we report all problems, not just the first
$problems = @()

function Test-Cmd {
  param([string]$Name)
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Write-OK    { param([string]$M) Write-Host "  [ OK ] $M" -ForegroundColor Green }
function Write-Fail  { param([string]$M) Write-Host "  [FAIL] $M" -ForegroundColor Red }
function Write-Warn2 { param([string]$M) Write-Host "  [WARN] $M" -ForegroundColor Yellow }

Write-Host ""
Write-Host "sdet-brain-win bootstrap check" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan

# --- Docker Desktop ---
Write-Host ""
Write-Host "Docker Desktop"
if (Test-Cmd 'docker') {
  try {
    docker info --format '{{.ServerVersion}}' > $null 2>&1
    if ($LASTEXITCODE -eq 0) {
      Write-OK "Docker daemon reachable"
    } else {
      Write-Fail "Docker installed but daemon not running. Open Docker Desktop."
      $problems += 'docker-daemon-not-running'
    }
  } catch {
    Write-Fail "Docker check failed: $_"
    $problems += 'docker-check-failed'
  }
} else {
  Write-Fail "docker CLI not found. Install: https://www.docker.com/products/docker-desktop"
  $problems += 'docker-not-installed'
}

# --- Ollama ---
Write-Host ""
Write-Host "Ollama"
if (Test-Cmd 'ollama') {
  $version = ollama --version 2>$null
  Write-OK "Ollama CLI installed ($version)"

  # Probe the service over HTTP first — `ollama list` is misleading when the
  # service is stopped (returns nothing instead of erroring), which would
  # have us misreport "bge-m3 not pulled" when actually Ollama is down.
  $ollamaUp = $false
  try {
    $tags = Invoke-RestMethod -Uri 'http://localhost:11434/api/tags' -TimeoutSec 3 -ErrorAction Stop
    $ollamaUp = $true
    Write-OK "Ollama service reachable on localhost:11434"
  } catch {
    Write-Fail "Ollama service NOT reachable on localhost:11434. Open the Ollama app or run: ollama serve"
    $problems += 'ollama-service-down'
  }

  if ($ollamaUp) {
    $modelNames = @($tags.models | ForEach-Object { $_.name })
    if ($modelNames -match 'bge-m3') {
      Write-OK "bge-m3 model pulled"
    } else {
      Write-Warn2 "bge-m3 not pulled. Run: ollama pull bge-m3"
      $problems += 'ollama-bge-m3-missing'
    }
  }
} else {
  Write-Fail "ollama CLI not found. Install: https://ollama.com/download/windows"
  $problems += 'ollama-not-installed'
}

# --- uv ---
Write-Host ""
Write-Host "uv"
if (Test-Cmd 'uv') {
  $uvVersion = uv --version 2>$null
  Write-OK "uv installed ($uvVersion)"
} else {
  Write-Fail "uv not found. Install: powershell -c `"irm https://astral.sh/uv/install.ps1 | iex`""
  $problems += 'uv-not-installed'
}

# --- Git ---
Write-Host ""
Write-Host "Git + GitHub CLI"
if (Test-Cmd 'git') {
  $gitVer = (git --version) -replace 'git version ', ''
  Write-OK "git installed ($gitVer)"
} else {
  Write-Fail "git not found. Install: winget install --id Git.Git"
  $problems += 'git-not-installed'
}
if (Test-Cmd 'gh') {
  Write-OK "gh CLI installed"
} else {
  Write-Warn2 "gh CLI not found (optional). Install: winget install --id GitHub.cli"
}

# --- Python 3.12 (managed via uv usually) ---
Write-Host ""
Write-Host "Python"
if (Test-Cmd 'python') {
  $py = python --version 2>$null
  Write-OK "Python available ($py) — uv will manage 3.12 venv anyway"
} else {
  Write-Warn2 "python not on PATH (uv will install one when you run uv sync)"
}

# --- NVIDIA driver + VRAM ---
Write-Host ""
Write-Host "NVIDIA"
if (Test-Cmd 'nvidia-smi') {
  try {
    $smi = nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>$null
    if ([string]::IsNullOrWhiteSpace($smi)) {
      Write-Warn2 "nvidia-smi returned empty output (driver issue?)"
      $problems += 'nvidia-smi-empty'
    } else {
      Write-OK "nvidia-smi reachable"
      Write-Host "    $smi" -ForegroundColor DarkGray
      $vramRaw = (nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1)
      if ([string]::IsNullOrWhiteSpace($vramRaw)) {
        Write-Warn2 "VRAM probe returned empty — skipping VRAM check"
        $problems += 'nvidia-smi-empty'
      } else {
        $vramMb = $vramRaw.Trim()
        $vramGb = [math]::Floor([int]$vramMb / 1024)
        if ($vramGb -ge $RequiredVramGb) {
          Write-OK "VRAM ${vramGb} GB >= required ${RequiredVramGb} GB"
        } else {
          Write-Warn2 "VRAM ${vramGb} GB is below recommended ${RequiredVramGb} GB"
          $problems += 'vram-low'
        }
      }
    }
  } catch {
    Write-Warn2 "nvidia-smi check failed: $_"
  }
} else {
  Write-Warn2 "nvidia-smi not on PATH. Ollama will fall back to CPU (slow)."
  $problems += 'nvidia-smi-missing'
}

# --- Free RAM ---
Write-Host ""
Write-Host "Memory"
try {
  $osCim = Get-CimInstance Win32_OperatingSystem
  $freeGb = [math]::Round($osCim.FreePhysicalMemory / 1MB, 1)
  $totalGb = [math]::Round($osCim.TotalVisibleMemorySize / 1MB, 1)
  Write-OK "Total RAM ${totalGb} GB, free ${freeGb} GB"
  if ($freeGb -lt 8) {
    Write-Warn2 "Less than 8 GB free — daily.py memory guard may skip runs."
  }
} catch {
  Write-Warn2 "RAM probe failed: $_"
}

# --- Free disk on project drive ---
Write-Host ""
Write-Host "Disk"
$drive = (Get-Item $PSScriptRoot).PSDrive
$freeDiskGb = [math]::Round($drive.Free / 1GB, 1)
Write-OK "Drive $($drive.Name): $freeDiskGb GB free"
if ($freeDiskGb -lt 10) {
  Write-Warn2 "Less than 10 GB free — Qdrant + snapshots may run out fast."
}

# --- Summary ---
Write-Host ""
Write-Host "Summary" -ForegroundColor Cyan
if ($problems.Count -eq 0) {
  Write-Host "  All green. Proceed with: uv sync, docker compose up -d qdrant, then uv run sdet-brain-server" -ForegroundColor Green
  exit 0
}
Write-Host "  Issues to resolve:" -ForegroundColor Yellow
foreach ($p in $problems) {
  Write-Host "    - $p"
}
exit 1
