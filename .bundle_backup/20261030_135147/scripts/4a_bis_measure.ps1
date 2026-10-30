$ErrorActionPreference = 'Stop'
$root = 'C:\xampp\htdocs\Payroll'
$backend = Join-Path $root 'backend'

Write-Host "=== step 1: apply patch v1 (idempotent) ==="
Push-Location $root
python scripts\4a_bis_patch.py
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { throw "STOP: patch v1 failed" }

Write-Host ""
Write-Host "=== step 1b: apply patch v2 (robust argon2) ==="
Push-Location $root
python scripts\4a_bis_patch_v2.py
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { throw "STOP: patch v2 failed" }

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
if ($beforeExit -ne 0) { Write-Host $beforeOut; throw "STOP: BEFORE failed" }
$beforeSec = [int]$swb.Elapsed.TotalSeconds
$beforeCount = ($beforeOut | Select-String -Pattern '(\d+) passed').Matches.Groups[1].Value
Write-Host "BEFORE elapsed: ${beforeSec}s; passed: $beforeCount"

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
if ($after1Exit -ne 0) { Write-Host $after1Out; throw "STOP: AFTER #1 failed" }
$after1Sec = [int]$swa1.Elapsed.TotalSeconds
Write-Host "AFTER #1 elapsed: ${after1Sec}s"

Write-Host ""
Write-Host "=== step 4: AFTER #2 (steady) ==="
Push-Location $backend
$swa2 = [System.Diagnostics.Stopwatch]::StartNew()
$after2Out = python -m pytest tests/test_adjustments.py tests/test_sheet.py -q --no-header 2>&1
$after2Exit = $LASTEXITCODE
$swa2.Stop()
Pop-Location
if ($after2Exit -ne 0) { Write-Host $after2Out; throw "STOP: AFTER #2 failed" }
$after2Sec = [int]$swa2.Elapsed.TotalSeconds
$after2Count = ($after2Out | Select-String -Pattern '(\d+) passed').Matches.Groups[1].Value
Write-Host "AFTER #2 elapsed: ${after2Sec}s; passed: $after2Count"

Write-Host ""
Write-Host "=== step 5: guard tests (env cleared) ==="
Push-Location $backend
Remove-Item Env:PAYROLL_TEST_TEMPLATE_DB -ErrorAction SilentlyContinue
Remove-Item Env:PAYROLL_TEST_FAST_HASH -ErrorAction SilentlyContinue
$guardOut = python -m pytest tests/test_security_argon2_guard.py -q --no-header 2>&1
$guardExit = $LASTEXITCODE
Pop-Location
if ($guardExit -ne 0) { Write-Host $guardOut; throw "STOP: guard failed" }
Write-Host $guardOut

Write-Host ""
Write-Host "=== step 6: SUMMARY ==="
$perTestBefore = [math]::Round([double]$beforeSec / [double]$beforeCount, 2)
$perTestAfter = [math]::Round([double]$after2Sec / [double]$after2Count, 2)
$perTestSaved = [math]::Round($perTestBefore - $perTestAfter, 2)
$estFull = [int](2435 - ($perTestSaved * 701))
if ($estFull -lt 300) { $estFull = 300 }
Write-Host ("BEFORE: ${beforeSec}s ($beforeCount passed); per-test ${perTestBefore}s")
Write-Host ("AFTER #1: ${after1Sec}s")
Write-Host ("AFTER #2: ${after2Sec}s ($after2Count passed); per-test ${perTestAfter}s")
Write-Host ("Per-test savings: ${perTestSaved}s")
Write-Host ("Estimated full-suite: ~${estFull}s (~$([int]($estFull/60)) min)")
if ($after2Sec -gt ($beforeSec * 0.85)) {
    Write-Host "WARN: still slow - fast path may not be active"
}
Write-Host "DONE. 4A-bis v2 complete."

Write-Host ""
Write-Host "=== step 7: drift diagnostic ==="
Push-Location $backend
$driftOut = python -m pytest tests/test_schema_drift.py -x -vv --tb=long --no-header 2>&1
$driftExit = $LASTEXITCODE
Pop-Location
$driftFile = Join-Path $root 'drift_diag.out'
$driftOut | Out-File -FilePath $driftFile -Encoding utf8
Write-Host "Drift test exit: $driftExit"
Write-Host "Drift diag saved to: $driftFile"
Write-Host ("--- first 60 lines ---")
$driftOut | Select-Object -First 60 | ForEach-Object { Write-Host $_ }

Write-Host ""
Write-Host "=== step 8: git commit patched files ==="
Push-Location $root
git add backend/app/core/security.py
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "STOP: git add failed" }
$staged = git diff --cached --name-only
if ($staged) {
    git commit -m "4A-bis v2: robust argon2 test override"
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "STOP: git commit failed" }
}
git log --oneline -3
Pop-Location

Write-Host ""
Write-Host "ALL DONE."
# END OF FILE
