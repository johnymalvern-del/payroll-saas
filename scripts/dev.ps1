# scripts\dev.ps1
$ErrorActionPreference = 'Stop'
$venvPython = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host "FAILED: .venv not found at $venvPython" -ForegroundColor Red
    Write-Host "  Next: run scripts\setup_windows.ps1 first" -ForegroundColor Yellow
    exit 1
}
Push-Location backend
try {
    Write-Host "Starting API on http://127.0.0.1:8000 (Ctrl+C to stop)" -ForegroundColor Cyan
    Write-Host "  Health:  http://127.0.0.1:8000/api/v1/health" -ForegroundColor DarkGray
    Write-Host "  Docs:    http://127.0.0.1:8000/api/docs" -ForegroundColor DarkGray
    & $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
} finally { Pop-Location }
