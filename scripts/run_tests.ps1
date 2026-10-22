# scripts\run_tests.ps1
$ErrorActionPreference = 'Stop'
$venvPython = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host "FAILED: .venv not found at $venvPython" -ForegroundColor Red
    Write-Host "  Next: run scripts\setup_windows.ps1 first" -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path '.env')) {
    Write-Host "FAILED: .env not found" -ForegroundColor Red
    Write-Host "  Next: run scripts\setup_windows.ps1 first" -ForegroundColor Yellow
    exit 1
}
Push-Location backend
try {
    & $venvPython -m pytest -v
    $exit = $LASTEXITCODE
} finally { Pop-Location }
if ($exit -eq 0) {
    Write-Host ""
    Write-Host "All tests passed." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Tests FAILED - scroll up to see which ones." -ForegroundColor Red
}
exit $exit
