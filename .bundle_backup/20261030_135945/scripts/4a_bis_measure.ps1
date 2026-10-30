$ErrorActionPreference = 'Stop'
$root = 'C:\xampp\htdocs\Payroll'
$backend = Join-Path $root 'backend'

Write-Host "=== step 1: apply v1 (idempotent) ==="
Push-Location $root
python scripts\4a_bis_patch.py
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { throw "STOP: v1 patch failed" }

Write-Host ""
Write-Host "=== step 1b: apply v3 (fix v2 arg order) ==="
Push-Location $root
python scripts\4a_bis_patch_v3.py
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { throw "STOP: v3 patch failed" }

Write-Host ""
Write-Host "=== step 2: BEFORE (env unset) ==="
Push-Location $backend
Remove-Item Env:PAYROLL_TEST_TEMPLATE_DB -ErrorAction SilentlyContinue
Remove-Item Env:PAYROLL_TEST_FAST_HASH -ErrorAction SilentlyContinue
$swb = [System.Diagnostics.Stopwatch]::StartNew()
$beforeOut = python -m pytest tests/test_adjustments.py tests/test_sheet.py -q --no-header 2>&1
$beforeExit = $LASTEXITCODE
$swb.Stop()
Pop-Location
$beforeSec = [int]$swb.Elapsed.TotalSeconds
$beforeCount = if ($beforeOut -match '(\d+) passed') { $matches[1] } else { "0" }
Write-Host "BEFORE: ${beforeSec}s; passed: $beforeCount; exit: $beforeExit"

Write-Host ""
Write-Host "=== step 3: AFTER #1 (bootstrap) ==="
Push-Location $backend
$env:PAYROLL_TEST_TEMPLATE_DB = '1'
$env:PAYROLL_TEST_FAST_HASH = '1'
$swa1 = [System.Diagnostics.Stopwatch]::StartNew()
$after1Out = python -m pytest tests/test_adjustments.py tests/test_sheet.py -q --no-header 2>&1
$after1Exit = $LASTEXITCODE
$swa1.Stop()
Pop-Location
$after1Sec = [int]$swa1.Elapsed.TotalSeconds
$after1Count = if ($after1Out -match '(\d+) passed') { $matches[1] } else { "0" }
Write-Host "AFTER #1: ${after1Sec}s; passed: $after1Count; exit: $after1Exit"

Write-Host ""
Write-Host "=== step 4: AFTER #2 (steady) ==="
Push-Location $backend
$swa2 = [System.Diagnostics.Stopwatch]::StartNew()
$after2Out = python -m pytest tests/test_adjustments.py tests/test_sheet.py -q --no-header 2>&1
$after2Exit = $LASTEXITCODE
$swa2.Stop()
Pop-Location
$after2Sec = [int]$swa2.Elapsed.TotalSeconds
$after2Count = if ($after2Out -match '(\d+) passed') { $matches[1] } else { "0" }
Write-Host "AFTER #2: ${after2Sec}s; passed: $after2Count; exit: $after2Exit"

Write-Host ""
Write-Host "=== step 5: guard tests (env cleared) ==="
Push-Location $backend
Remove-Item Env:PAYROLL_TEST_TEMPLATE_DB -ErrorAction SilentlyContinue
Remove-Item Env:PAYROLL_TEST_FAST_HASH -ErrorAction SilentlyContinue
$guardOut = python -m pytest tests/test_security_argon2_guard.py -q --no-header 2>&1
$guardExit = $LASTEXITCODE
Pop-Location
Write-Host "guard exit: $guardExit"
$guardOut | Select-Object -Last 8 | ForEach-Object { Write-Host $_ }

Write-Host ""
Write-Host "=== step 6: SUMMARY ==="
if ([int]$beforeCount -gt 0 -and [int]$after2Count -gt 0) {
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
} else {
    Write-Host "Cannot compute summary (some runs failed to parse pass count)."
    Write-Host "BEFORE: ${beforeSec}s exit=$beforeExit"
    Write-Host "AFTER #1: ${after1Sec}s exit=$after1Exit"
    Write-Host "AFTER #2: ${after2Sec}s exit=$after2Exit"
}

Write-Host ""
Write-Host "=== step 7: drift diagnostic ==="
Push-Location $backend
$driftOut = python -m pytest tests/test_schema_drift.py -x -vv --tb=long --no-header 2>&1
$driftExit = $LASTEXITCODE
Pop-Location
$driftOut | Out-File -FilePath (Join-Path $root 'drift_diag.out') -Encoding utf8
Write-Host "drift exit: $driftExit; saved drift_diag.out"

$driftTestPath = Join-Path $backend 'tests\test_schema_drift.py'
if (Test-Path $driftTestPath) {
    Get-Content $driftTestPath -Raw | Out-File -FilePath (Join-Path $root 'drift_source.out') -Encoding utf8
    Write-Host "saved drift_source.out ($((Get-Item (Join-Path $root 'drift_source.out')).Length) bytes)"
}

Write-Host ""
Write-Host "=== step 8: git commit patched files ==="
Push-Location $root
git add backend/app/core/security.py backend/tests/test_security_argon2_guard.py
$staged = git diff --cached --name-only
if ($staged) {
    git commit -m "4A-bis v3: fix v2 arg-order bug, guard test skips when patch absent"
}
git log --oneline -3
Pop-Location

Write-Host ""
Write-Host "============= PASTE THIS BLOCK BACK ============="
Write-Host "SUMMARY:"
Write-Host "  BEFORE: ${beforeSec}s ($beforeCount passed, exit $beforeExit)"
Write-Host "  AFTER #1: ${after1Sec}s ($after1Count passed, exit $after1Exit)"
Write-Host "  AFTER #2: ${after2Sec}s ($after2Count passed, exit $after2Exit)"
Write-Host "  Guard exit: $guardExit"
if ([int]$beforeCount -gt 0 -and [int]$after2Count -gt 0) {
    Write-Host ("  Estimated full: ${estFull}s (~$([int]($estFull/60)) min)")
}
Write-Host ""
Write-Host "DRIFT FAILURE (first 25 lines):"
$driftOut | Select-Object -First 25 | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "DRIFT SOURCE (tests/test_schema_drift.py, first 120 lines):"
if (Test-Path (Join-Path $root 'drift_source.out')) {
    Get-Content (Join-Path $root 'drift_source.out') | Select-Object -First 120 | ForEach-Object { Write-Host $_ }
}
Write-Host "============= END PASTE ============="
Write-Host ""
Write-Host "ALL DONE."
# END OF FILE
