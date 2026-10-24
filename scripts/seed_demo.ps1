# scripts\seed_demo.ps1
# Creates a demo tenant with one user per role.
# REFUSES to run unless ENVIRONMENT is development or test.
# REFUSES to re-run if the demo tenant already exists.

$ErrorActionPreference = 'Stop'

$envValue = $env:ENVIRONMENT
if ([string]::IsNullOrWhiteSpace($envValue)) {
    Write-Host "REFUSED: ENVIRONMENT is not set. Set it to 'development' or 'test' to run the demo seed." -ForegroundColor Red
    exit 1
}
if ($envValue -ne 'development' -and $envValue -ne 'test') {
    Write-Host "REFUSED: ENVIRONMENT=$envValue. The demo seed only runs in development or test." -ForegroundColor Red
    exit 1
}

cd C:\xampp\htdocs\Payroll

$env:PYTHONPATH = (Resolve-Path 'backend').Path
try {
    & .\.venv\Scripts\python.exe -m app.scripts.seed_demo
    $code = $LASTEXITCODE
} finally {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
}

if ($code -ne 0) {
    Write-Host "demo seed failed (exit $code)" -ForegroundColor Red
    exit $code
}

Write-Host ""
Write-Host "Demo tenant ready." -ForegroundColor Green
Write-Host ""
Write-Host "Open the interactive API:"
Write-Host "  1. Browse to http://localhost:8000/docs"
Write-Host "  2. Click Authorize (top right) - not needed for the tenant header,"
Write-Host "     which you set on each request as shown below."
Write-Host ""
Write-Host "Log in as payroll_admin and copy the access_token from the response:"
Write-Host "  curl -X POST http://localhost:8000/api/v1/auth/login ^"
Write-Host "       -H `"Content-Type: application/json`" ^"
Write-Host "       -H `"X-Tenant-Slug: demo`" ^"
Write-Host "       -d `"{\`"identifier\`":\`"demo-admin\`",\`"password\`":\`"DemoAdmin123!\`"}`""
Write-Host ""
Write-Host "Then call the company endpoint:"
Write-Host "  curl -X GET http://localhost:8000/api/v1/company ^"
Write-Host "       -H `"X-Tenant-Slug: demo`" ^"
Write-Host "       -H `"Authorization: Bearer <paste-access-token>`""
Write-Host ""
Write-Host "Try a PATCH as payroll_admin (tax_number is allowed):"
Write-Host "  curl -X PATCH http://localhost:8000/api/v1/company ^"
Write-Host "       -H `"Content-Type: application/json`" ^"
Write-Host "       -H `"X-Tenant-Slug: demo`" ^"
Write-Host "       -H `"Authorization: Bearer <paste-access-token>`" ^"
Write-Host "       -d `"{\`"row_version\`":1,\`"tax_number\`":\`"9009999999\`"}`""
Write-Host ""
Write-Host "Try the same PATCH as the demo-hr user (403 forbidden_field):"
Write-Host "  log in first as demo-hr / DemoHr123!"
Write-Host ""
Write-Host "Demo users (development-only passwords):"
Write-Host "  demo-admin   / DemoAdmin123!    role: payroll_admin"
Write-Host "  demo-hr      / DemoHr123!       role: hr"
Write-Host "  demo-mgr     / DemoMgr123!      role: manager"
Write-Host "  demo-emp     / DemoEmp123!      role: employee"
Write-Host "  demo-audit   / DemoAudit123!    role: auditor"
Write-Host ""