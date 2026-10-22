# scripts\setup_windows.ps1
# One-time setup for running the payroll backend natively on Windows.
#
# Run from the repository root:
#     powershell -NoExit -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1

$ErrorActionPreference = 'Stop'

function Fail {
    param([string]$Step, [string]$Command, [string]$NextAction)
    Write-Host ""
    Write-Host "FAILED: $Step" -ForegroundColor Red
    if ($Command) { Write-Host "  Command: $Command" -ForegroundColor Yellow }
    if ($NextAction) { Write-Host "  Next:    $NextAction" -ForegroundColor Yellow }
    exit 1
}

function Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

Step "Checking prerequisites"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Fail "Python not found" "python --version" "Install Python 3.12 from https://www.python.org/downloads/release/python-3129/ and tick 'Add python.exe to PATH'."
}
$pyVersion = (& python --version 2>&1).ToString()
if ($pyVersion -notmatch '3\.12') {
    Fail "Python is not 3.12" "python --version" "You have '$pyVersion'. Install Python 3.12 from https://www.python.org/downloads/release/python-3129/."
}
Write-Host "  Python: $pyVersion"

$psql = Get-Command psql -ErrorAction SilentlyContinue
if (-not $psql) {
    Fail "psql not found on PATH" "psql --version" "Add C:\Program Files\PostgreSQL\16\bin to your user PATH, close and reopen PowerShell."
}
$psqlVersion = (& psql --version 2>&1).ToString()
if ($psqlVersion -notmatch '16\.') {
    Fail "PostgreSQL is not 16" "psql --version" "You have '$psqlVersion'. Install PostgreSQL 16 from https://www.enterprisedb.com/downloads/postgres-postgresql-downloads."
}
Write-Host "  PostgreSQL: $psqlVersion"

Step "Creating virtual environment at .venv"
if (-not (Test-Path '.venv')) {
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "venv creation" "python -m venv .venv" "Check that the current directory is writable." }
}
$venvPython = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) { Fail "venv python not found" $venvPython "Delete .venv and re-run this script." }
Write-Host "  $venvPython"

Step "Installing dependencies into .venv (may take 3-5 minutes)"
Push-Location backend
try {
    & $venvPython -m pip install --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) { Fail "pip upgrade" "$venvPython -m pip install --upgrade pip" "Check internet connectivity." }
    & $venvPython -m pip install -e ".[dev]"
    if ($LASTEXITCODE -ne 0) { Fail "pip install -e .[dev]" "$venvPython -m pip install -e .[dev]" "Read the pip error above; most often a package fails to compile." }
} finally { Pop-Location }

Step "Writing .env"
if (Test-Path '.env') {
    Write-Host "  .env already exists - not overwriting." -ForegroundColor DarkYellow
} else {
    $envExample = Get-Content '.env.example' -Raw
    $envNative = $envExample `
        -replace 'DATABASE_URL_CONTROL=.*', 'DATABASE_URL_CONTROL=postgresql+psycopg://payroll_app:payroll_app_dev_password@localhost:5432/payroll_control' `
        -replace 'DATABASE_URL_CONTROL_ADMIN=.*', 'DATABASE_URL_CONTROL_ADMIN=postgresql+psycopg://payroll_app:payroll_app_dev_password@localhost:5432/payroll_control' `
        -replace 'DATABASE_URL_TENANT_TEMPLATE=.*', 'DATABASE_URL_TENANT_TEMPLATE=postgresql+psycopg://payroll_app:payroll_app_dev_password@localhost:5432/{tenant_db}' `
        -replace 'DATABASE_URL_TENANT_ADMIN_TEMPLATE=.*', 'DATABASE_URL_TENANT_ADMIN_TEMPLATE=postgresql+psycopg://payroll_test:payroll_test_dev_password@localhost:5432/{tenant_db}' `
        -replace 'REDIS_URL=.*', 'REDIS_URL=' `
        -replace 'S3_ENDPOINT=.*', 'S3_ENDPOINT=' `
        -replace 'CLAMAV_HOST=.*', 'CLAMAV_HOST=' `
        -replace 'ENVIRONMENT=.*', 'ENVIRONMENT=development'
    Set-Content -Path '.env' -Value $envNative -Encoding utf8 -NoNewline
    Write-Host "  .env written."
}

Step "Verifying control database connectivity as payroll_app"
$env:PGPASSWORD = 'payroll_app_dev_password'
$probeOutput = & psql -U payroll_app -h localhost -d payroll_control -c "SELECT 1;" 2>&1
$probeExit = $LASTEXITCODE
Remove-Item Env:PGPASSWORD
if ($probeExit -ne 0) {
    Write-Host $probeOutput -ForegroundColor Red
    Fail "Cannot connect to payroll_control as payroll_app" "psql -U payroll_app -h localhost -d payroll_control" "Roles and DB must exist (see A3). Password must be payroll_app_dev_password."
}
Write-Host "  Connection OK."

Step "Running control database migrations"
Push-Location backend
try {
    & $venvPython -m alembic -c alembic.ini -n control upgrade head
    if ($LASTEXITCODE -ne 0) { Fail "Alembic control upgrade" "$venvPython -m alembic -c alembic.ini -n control upgrade head" "Read the error above." }
} finally { Pop-Location }

Step "Seeding ZA country profile template"
Push-Location backend
try {
    & $venvPython -m app.scripts.seed
    if ($LASTEXITCODE -ne 0) { Fail "Seed script" "$venvPython -m app.scripts.seed" "Read the error above." }
} finally { Pop-Location }

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next:"
Write-Host "  powershell -NoExit -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1"
Write-Host "  powershell -NoExit -ExecutionPolicy Bypass -File .\scripts\dev.ps1"
Write-Host ""
