# Seed tenant_demo (B-2). Run from repo root: .\scripts\seed_demo.ps1 [--reset|--keep]
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "venv missing at $py"; exit 1 }
Push-Location $root
try {
    & $py -m app.seed.demo_seed @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}