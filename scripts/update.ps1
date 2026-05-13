<#
.SYNOPSIS
  Update sdet-brain-win to the latest code from the windows-port branch.

.DESCRIPTION
  Performs the full update sequence safely:
    1. git pull (windows-port)
    2. uv sync --extra dev (if pyproject.toml changed)
    3. Stop server processes (if running)
    4. Print restart hint

  Designed for the daily / weekly cadence of pulling upstream fixes.
  Does NOT restart Qdrant container - Qdrant data is persistent, no
  reason to touch it.

.EXAMPLE
  PS> .\scripts\update.ps1
  PS> .\scripts\update.ps1 -SkipSync   # just git pull, skip uv sync
  PS> .\scripts\update.ps1 -Force      # don't ask before stopping the server
#>

[CmdletBinding()]
param(
  [switch]$SkipSync,
  [switch]$Force
)

$ErrorActionPreference = 'Stop'

function Write-Step  { param([string]$M) Write-Host ""; Write-Host "==> $M" -ForegroundColor Cyan }
function Write-OK    { param([string]$M) Write-Host "    OK  $M" -ForegroundColor Green }
function Write-Warn2 { param([string]$M) Write-Host "    !!  $M" -ForegroundColor Yellow }

# --- 1. Sanity: are we in the repo? ---
$repoRoot = (Get-Item $PSScriptRoot).Parent.FullName
if (-not (Test-Path "$repoRoot\pyproject.toml") -or -not (Test-Path "$repoRoot\.git")) {
    Write-Host "ERROR: $repoRoot does not look like the sdet-brain-win repo" -ForegroundColor Red
    exit 1
}
Set-Location $repoRoot
Write-OK "Repo root: $repoRoot"

# --- 2. Capture pre-pull state ---
Write-Step "Pre-pull state"
$beforeSha = (git rev-parse HEAD).Trim()
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
Write-OK "Branch: $branch (HEAD $($beforeSha.Substring(0,7)))"
$pyprojectBeforeHash = (Get-FileHash pyproject.toml -Algorithm SHA1).Hash

if ($branch -ne 'windows-port') {
    Write-Warn2 "You are on '$branch', not 'windows-port'. Updating anyway, but expect divergence."
}

# --- 3. git pull ---
Write-Step "git pull (fetch + fast-forward)"
git pull --ff-only
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pull failed (probably conflict or non-fast-forward divergence)" -ForegroundColor Red
    Write-Host "Resolve manually then re-run." -ForegroundColor Red
    exit 1
}
$afterSha = (git rev-parse HEAD).Trim()
if ($afterSha -eq $beforeSha) {
    Write-OK "Already up to date (no new commits)."
} else {
    Write-OK "Pulled $($beforeSha.Substring(0,7)) -> $($afterSha.Substring(0,7))"
    Write-Host ""
    Write-Host "New commits:" -ForegroundColor DarkGray
    git log --oneline "$beforeSha..HEAD"
}

# --- 4. uv sync if pyproject.toml changed ---
$pyprojectAfterHash = (Get-FileHash pyproject.toml -Algorithm SHA1).Hash
$pyprojectChanged = ($pyprojectBeforeHash -ne $pyprojectAfterHash)

if ($SkipSync) {
    Write-Warn2 "Skipping uv sync (--SkipSync passed)"
} elseif ($pyprojectChanged -or ($afterSha -ne $beforeSha)) {
    Write-Step "uv sync --extra dev (pyproject changed or new commits arrived)"
    & "$env:USERPROFILE\.local\bin\uv.exe" sync --extra dev
    if ($LASTEXITCODE -ne 0) {
        Write-Host "uv sync failed - inspect output above" -ForegroundColor Red
        exit 1
    }
    Write-OK "Dependencies synced"
} else {
    Write-OK "pyproject.toml unchanged - uv sync skipped"
}

# --- 5. Stop running server (if any) so user can restart with new code ---
Write-Step "Server process check"
$serverProcs = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
    try { $_.MainModule.FileName -like "*sdet-brain-win*" -or $_.CommandLine -like "*sdet-brain*" } catch { $false }
}
if ($null -ne $serverProcs -and $serverProcs.Count -gt 0) {
    Write-Warn2 "Found $($serverProcs.Count) sdet-brain server process(es) running"
    if (-not $Force) {
        $confirm = Read-Host "    Stop them now? (Y/n)"
        if ($confirm -eq 'n' -or $confirm -eq 'N') {
            Write-Warn2 "Leaving server running - changes won't take effect until next manual restart"
        } else {
            $serverProcs | Stop-Process -Force
            Write-OK "Stopped"
        }
    } else {
        $serverProcs | Stop-Process -Force
        Write-OK "Stopped (--Force)"
    }
} else {
    Write-OK "No server process running"
}

# --- 6. Summary + next-step hint ---
Write-Step "Done"
if ($afterSha -ne $beforeSha) {
    Write-Host "    Updated $($beforeSha.Substring(0,7)) -> $($afterSha.Substring(0,7))" -ForegroundColor Green
} else {
    Write-Host "    Already current" -ForegroundColor Green
}

Write-Host ""
Write-Host "Next:"
Write-Host "  1. Make sure Qdrant is up:    docker ps --filter name=sdet-brain-qdrant"
Write-Host "  2. Start the server:          uv run sdet-brain-server"
Write-Host "  3. Optional smoke health:     Invoke-RestMethod http://localhost:8080/health"
Write-Host ""
