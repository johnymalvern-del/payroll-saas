$ErrorActionPreference = 'Stop'
$root = 'C:\xampp\htdocs\Payroll'
$backend = Join-Path $root 'backend'

function Parse-Passed([object[]]$lines) {
    $txt = ($lines | Out-String)
    if ($txt -match '(\d+) passed') { return [int]$matches[1] }
    return 0
}

Write-Host "=== step 1: patch medical_scheme_members (NOT NULL) ==="
Push-Location $root
python scripts\patch_012.py
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { throw "STOP: patch_012 failed" }

Write-Host ""
Write-Host "=== step 2: verify import ==="
Push-Location $backend
python -c "from app.db.tenant.models.people import Employee; print('people OK, columns:', len(list(Employee.__table__.columns)))"
if ($LASTEXITCODE -ne 0) { throw "STOP: people import failed" }

Write-Host ""
Write-Host "=== step 3: drift test (must pass) ==="
Remove-Item Env:PAYROLL_TEST_TEMPLATE_DB -ErrorAction SilentlyContinue
Remove-Item Env:PAYROLL_TEST_FAST_HASH -ErrorAction SilentlyContinue
$driftOut = python -m pytest tests/test_schema_drift.py -q --no-header 2>&1
$driftExit = $LASTEXITCODE
$driftOut | Select-Object -Last 3 | ForEach-Object { Write-Host $_ }
if ($driftExit -ne 0) { throw "STOP: drift failed" }

Write-Host ""
Write-Host "=== step 4: BEFORE (env unset) ==="
$swb = [System.Diagnostics.Stopwatch]::StartNew()
$beforeOut = python -m pytest tests/test_adjustments.py tests/test_sheet.py -q --no-header 2>&1
$beforeExit = $LASTEXITCODE
$swb.Stop()
$beforeSec = [int]$swb.Elapsed.TotalSeconds
$beforeCount = Parse-Passed $beforeOut
Write-Host "BEFORE: ${beforeSec}s; passed: $beforeCount; exit: $beforeExit"
if ($beforeExit -ne 0) { $beforeOut | Select-Object -Last 25 | ForEach-Object { Write-Host $_ } }

Write-Host ""
Write-Host "=== step 5: AFTER #1 (bootstrap) ==="
$env:PAYROLL_TEST_TEMPLATE_DB = '1'
$env:PAYROLL_TEST_FAST_HASH = '1'
$swa1 = [System.Diagnostics.Stopwatch]::StartNew()
$after1Out = python -m pytest tests/test_adjustments.py tests/test_sheet.py tests/test_fastpath_diagnostic.py -q --no-header 2>&1
$after1Exit = $LASTEXITCODE
$swa1.Stop()
$after1Sec = [int]$swa1.Elapsed.TotalSeconds
$after1Count = Parse-Passed $after1Out
Write-Host "AFTER #1: ${after1Sec}s; passed: $after1Count; exit: $after1Exit"
if ($after1Exit -ne 0) { $after1Out | Select-Object -Last 25 | ForEach-Object { Write-Host $_ } }

Write-Host ""
Write-Host "=== step 6: AFTER #2 with durations ==="
$swa2 = [System.Diagnostics.Stopwatch]::StartNew()
$after2Out = python -m pytest tests/test_adjustments.py tests/test_sheet.py tests/test_fastpath_diagnostic.py -q --no-header --durations=10 --durations-min=0.3 2>&1
$after2Exit = $LASTEXITCODE
$swa2.Stop()
$after2Sec = [int]$swa2.Elapsed.TotalSeconds
$after2Count = Parse-Passed $after2Out
Write-Host "AFTER #2: ${after2Sec}s; passed: $after2Count; exit: $after2Exit"
Write-Host "--- AFTER #2 durations ---"
$after2Out | Select-String -Pattern '^\d+\.\d+s\s+(setup|call|teardown)' | ForEach-Object { Write-Host ("  " + $_.Line.Trim()) }

Write-Host ""
Write-Host "=== step 7: guard tests ==="
Remove-Item Env:PAYROLL_TEST_TEMPLATE_DB -ErrorAction SilentlyContinue
Remove-Item Env:PAYROLL_TEST_FAST_HASH -ErrorAction SilentlyContinue
$guardOut = python -m pytest tests/test_security_argon2_guard.py -q --no-header 2>&1
$guardExit = $LASTEXITCODE
Pop-Location
Write-Host "guard: $guardExit"
$guardOut | Select-Object -Last 2 | ForEach-Object { Write-Host $_ }

Write-Host ""
Write-Host "=== step 8: SUMMARY ==="
$estFull = -1
if ($beforeCount -gt 0 -and $after2Count -gt 0) {
    $perTestBefore = [math]::Round([double]$beforeSec / [double]$beforeCount, 2)
    $perTestAfter = [math]::Round([double]$after2Sec / [double]$after2Count, 2)
    $perTestSaved = [math]::Round($perTestBefore - $perTestAfter, 2)
    $estFull = [int](2435 - ($perTestSaved * 701))
    if ($estFull -lt 300) { $estFull = 300 }
    Write-Host ("BEFORE: ${beforeSec}s ($beforeCount tests); per-test ${perTestBefore}s")
    Write-Host ("AFTER #1: ${after1Sec}s")
    Write-Host ("AFTER #2: ${after2Sec}s ($after2Count tests); per-test ${perTestAfter}s")
    Write-Host ("Per-test savings: ${perTestSaved}s")
    Write-Host ("Estimated full-suite: ~${estFull}s (~$([int]($estFull/60)) min)")
}

Write-Host ""
Write-Host "=== step 9: commit ==="
Push-Location $root
git add backend/app/db/tenant/models/people.py scripts/run_013.ps1
$rc = $LASTEXITCODE
if ($rc -ne 0) { Write-Host "git add exit: $rc" }
$staged = git diff --cached --name-only
if ($staged) {
    git commit -m "4A-bis v6: fix medical_scheme_members NOT NULL, add durations to measure"
    Write-Host "commit exit: $LASTEXITCODE"
}
git log --oneline -3
Pop-Location

Write-Host ""
Write-Host "============= PASTE THIS BLOCK BACK ============="
Write-Host "DRIFT: exit=$driftExit"
$driftOut | Select-Object -Last 2 | ForEach-Object { Write-Host "  $_" }
Write-Host ""
Write-Host "SUMMARY:"
Write-Host "  BEFORE: ${beforeSec}s ($beforeCount passed, exit $beforeExit)"
Write-Host "  AFTER #1: ${after1Sec}s ($after1Count passed, exit $after1Exit)"
Write-Host "  AFTER #2: ${after2Sec}s ($after2Count passed, exit $after2Exit)"
Write-Host "  Guard exit: $guardExit"
if ($estFull -gt 0) {
    Write-Host ("  Estimated full: ${estFull}s (~$([int]($estFull/60)) min)")
}
Write-Host ""
Write-Host "AFTER #2 durations (setup/call/teardown):"
$after2Out | Select-String -Pattern '^\d+\.\d+s\s+(setup|call|teardown)' | Select-Object -First 15 | ForEach-Object { Write-Host ("  " + $_.Line.Trim()) }
Write-Host "============= END PASTE ============="
Write-Host ""
Write-Host "ALL DONE."
# END OF FILE
