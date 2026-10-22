# scripts\doctor.ps1
# Read-only diagnostic. Prints one line per check. Never modifies anything.
# Exit code: 0 if all checks pass, 1 if any fail.

$ErrorActionPreference = 'Stop'

$failures = 0
function Report {
    param([string]$Name, [bool]$Ok, [string]$Detail = "")
    if ($Ok) {
        Write-Host ("  [ OK ]  {0,-45} {1}" -f $Name, $Detail) -ForegroundColor Green
    } else {
        Write-Host ("  [FAIL]  {0,-45} {1}" -f $Name, $Detail) -ForegroundColor Red
        $script:failures += 1
    }
}

Write-Host ""
Write-Host "payroll-saas doctor" -ForegroundColor Cyan
Write-Host ""

# 1. Python version
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
    $pyVer = (& python --version 2>&1).ToString()
    Report "Python on PATH" ($LASTEXITCODE -eq 0 -and $pyVer -match '3\.12') $pyVer
} else {
    Report "Python on PATH" $false "not found"
}

# 2. Virtual environment
$venvPython = Join-Path (Get-Location) '.venv\Scripts\python.exe'
$venvOk = Test-Path $venvPython
$venvDetail = if ($venvOk) { (Split-Path $venvPython -Parent | Split-Path -Parent) } else { "run scripts\setup_windows.ps1" }
Report "Virtual environment (.venv)" $venvOk $venvDetail

# 3. PostgreSQL reachable
$psql = Get-Command psql -ErrorAction SilentlyContinue
if ($psql) {
    $pgVersion = (& psql --version 2>&1).ToString()
    Report "psql on PATH" ($LASTEXITCODE -eq 0 -and $pgVersion -match '16\.') $pgVersion
} else {
    Report "psql on PATH" $false "not found"
}

$env:PGPASSWORD = "payroll_app_dev_password"
$connect = (& psql -U payroll_app -h localhost -d postgres -c "SELECT 1;" 2>&1).ToString()
$connectExit = $LASTEXITCODE
Remove-Item Env:PGPASSWORD
Report "PostgreSQL reachable as payroll_app" ($connectExit -eq 0) $(if ($connectExit -eq 0) { "port 5432 OK" } else { "cannot connect" })

# 4. Role payroll_app exists
$env:PGPASSWORD = "postgres"
$roleCheck = (& psql -U postgres -h localhost -d postgres -t -A -c "SELECT 1 FROM pg_roles WHERE rolname='payroll_app';" 2>&1).ToString()
$roleExit = $LASTEXITCODE
Remove-Item Env:PGPASSWORD
Report "Role payroll_app exists" ($roleExit -eq 0 -and $roleCheck.Trim() -eq '1') $(if ($roleCheck.Trim() -eq '1') { "present" } else { "missing" })

# 5. Role payroll_test has CREATEDB
$env:PGPASSWORD = "postgres"
$testRoleRow = (& psql -U postgres -h localhost -d postgres -t -A -c "SELECT rolcreatedb FROM pg_roles WHERE rolname='payroll_test';" 2>&1).ToString()
$testRoleExit = $LASTEXITCODE
Remove-Item Env:PGPASSWORD
$testRoleHasDb = $testRoleRow.Trim() -eq 't'
Report "Role payroll_test has CREATEDB" ($testRoleExit -eq 0 -and $testRoleHasDb) $(if ($testRoleHasDb) { "present" } else { "missing or lacks CREATEDB" })

# 6. Control database exists and has subscriber table
$env:PGPASSWORD = "payroll_app_dev_password"
$ctrlExists = (& psql -U payroll_app -h localhost -d payroll_control -t -A -c "SELECT 1;" 2>&1).ToString()
$ctrlExit = $LASTEXITCODE
Report "payroll_control reachable" ($ctrlExit -eq 0) $(if ($ctrlExit -eq 0) { "OK" } else { "missing" })

if ($ctrlExit -eq 0) {
    $subscriber = (& psql -U payroll_app -h localhost -d payroll_control -t -A -c "SELECT to_regclass('public.subscriber');" 2>&1).ToString()
    Report "payroll_control has subscriber table" ($subscriber.Trim() -eq 'subscriber') $(if ($subscriber.Trim() -eq 'subscriber') { "present" } else { "MISSING" })
} else {
    Report "payroll_control has subscriber table" $false "cannot query"
}

# 7. Alembic revision
if ($venvOk -and $ctrlExit -eq 0) {
    Push-Location backend
    try {
        $rev = (& $venvPython -m alembic -c alembic.ini -n control current 2>&1).ToString()
        $revExit = $LASTEXITCODE
    } finally { Pop-Location }
    $revShort = ($rev -split "`n" | Where-Object { $_ -match 'ctl_|head' } | Select-Object -First 1)
    Report "Alembic control current revision" ($revExit -eq 0) $(if ($revShort) { $revShort.Trim() } else { "unknown" })
} else {
    Report "Alembic control current revision" $false "prerequisites failed"
}
Remove-Item Env:PGPASSWORD

# 8. Tenant database count
$env:PGPASSWORD = "postgres"
$tenantCount = (& psql -U postgres -h localhost -d postgres -t -A -c "SELECT count(*) FROM pg_database WHERE datname LIKE 'tenant_%';" 2>&1).ToString()
$tenantExit = $LASTEXITCODE
Remove-Item Env:PGPASSWORD
Report "Tenant database count" ($tenantExit -eq 0) $(if ($tenantExit -eq 0) { "$($tenantCount.Trim()) tenant DBs" } else { "cannot query" })

Write-Host ""
if ($failures -eq 0) {
    Write-Host "All checks passed." -ForegroundColor Green
    Write-Host ""
    exit 0
} else {
    Write-Host "$failures check(s) failed - see [FAIL] lines above." -ForegroundColor Red
    Write-Host ""
    exit 1
}
