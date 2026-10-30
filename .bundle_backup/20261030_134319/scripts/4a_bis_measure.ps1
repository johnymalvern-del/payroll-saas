$ErrorActionPreference = 'Stop'
$root = 'C:\xampp\htdocs\Payroll'
$backend = Join-Path $root 'backend'

Write-Host "=== step 1: apply patch ==="
Push-Location $root
python scripts\4a_bis_patch.py
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { throw "STOP: patch failed" }

Write-Host ""
Write-Host "=== step 2: BEFORE measurement (env vars unset) ==="
Push-Location $backend
Remove-Item Env:PAYROLL_TEST_TEMPLATE_DB -ErrorAction SilentlyContinue
Remove-Item Env:PAYROLL_TEST_FAST_HASH -ErrorAction SilentlyContinue
$swb = [System.Diagnostics.Stopwatch]::StartNew()
$beforeOut = python -m pytest tests/test_adjustments.py tests/test_sheet.py -v --durations=25 --durations-min=0.3 --no-header 2>&1
$beforeExit = $LASTEXITCODE
$swb.Stop()
Pop-Location
if ($beforeExit -ne 0) { Write-Host $beforeOut; throw "STOP: BEFORE failed" }
$beforeSec = [int]$swb.Elapsed.TotalSeconds
Write-Host "BEFORE elapsed: ${beforeSec}s"
$beforeOut | Select-String -Pattern '^\d+\.\d+s\s+(setup|call|teardown)' | ForEach-Object { Write-Host ("  " + $_.Line.Trim()) }

Write-Host ""
Write-Host "=== step 3: AFTER run #1 (bootstrap included) ==="
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
Write-Host "AFTER #1 elapsed: ${after1Sec}s (bootstrap included)"

Write-Host ""
Write-Host "=== step 4: AFTER run #2 (steady state) ==="
Push-Location $backend
$swa2 = [System.Diagnostics.Stopwatch]::StartNew()
$after2Out = python -m pytest tests/test_adjustments.py tests/test_sheet.py -q --no-header 2>&1
$after2Exit = $LASTEXITCODE
$swa2.Stop()
Pop-Location
if ($after2Exit -ne 0) { Write-Host $after2Out; throw "STOP: AFTER #2 failed" }
$after2Sec = [int]$swa2.Elapsed.TotalSeconds
Write-Host "AFTER #2 elapsed: ${after2Sec}s"
$after2Out | Select-String -Pattern '\d+ passed' | Select-Object -Last 1 | ForEach-Object { Write-Host ("  " + $_.Line.Trim()) }

Write-Host ""
Write-Host "=== step 5: guard tests (env cleared) ==="
Push-Location $backend
Remove-Item Env:PAYROLL_TEST_TEMPLATE_DB -ErrorAction SilentlyContinue
Remove-Item Env:PAYROLL_TEST_FAST_HASH -ErrorAction SilentlyContinue
$guardOut = python -m pytest tests/test_security_argon2_guard.py -q --no-header 2>&1
$guardExit = $LASTEXITCODE
Pop-Location
if ($guardExit -ne 0) { Write-Host $guardOut; throw "STOP: guard tests failed" }
Write-Host $guardOut

Write-Host ""
Write-Host "=== step 6: fast subset (-m 'not slow') ==="
Push-Location $backend
$env:PAYROLL_TEST_FAST_HASH = '1'
$swf = [System.Diagnostics.Stopwatch]::StartNew()
$fastOut = python -m pytest tests -q -m "not slow" --no-header 2>&1
$fastExit = $LASTEXITCODE
$swf.Stop()
Pop-Location
Remove-Item Env:PAYROLL_TEST_FAST_HASH -ErrorAction SilentlyContinue
if ($fastExit -ne 0) { Write-Host $fastOut; throw "STOP: fast subset failed" }
$fastSec = [int]$swf.Elapsed.TotalSeconds
$fastOut | Select-String -Pattern '\d+ passed' | Select-Object -Last 1 | ForEach-Object { Write-Host ("  " + $_.Line.Trim()) }

Write-Host ""
Write-Host "=== step 7: SUMMARY ==="
$perTestBefore = [math]::Round([double]$beforeSec / 15.0, 2)
$perTestAfter = [math]::Round([double]$after2Sec / 15.0, 2)
$perTestSaved = [math]::Round($perTestBefore - $perTestAfter, 2)
$estSaved = $perTestSaved * 701
$estFull = [int](2435 - $estSaved)
if ($estFull -lt 300) { $estFull = 300 }
Write-Host ("BEFORE (2 files): ${beforeSec}s; per-test ${perTestBefore}s")
Write-Host ("AFTER #1 (bootstrap): ${after1Sec}s")
Write-Host ("AFTER #2 (steady): ${after2Sec}s; per-test ${perTestAfter}s")
Write-Host ("Per-test savings: ${perTestSaved}s")
Write-Host ("Fast subset: ${fastSec}s")
Write-Host ("Estimated full-suite time after change: ~${estFull}s (~$([int]($estFull/60)) min) vs 2435s baseline")
if ($after2Sec -gt ($beforeSec * 0.85)) {
    Write-Host "WARN: AFTER not substantially faster than BEFORE - fast path may not be active."
}
Write-Host "DONE. 4A-bis complete."

Write-Host ""
Write-Host "=== step 8: git add + commit patched files ==="
Push-Location $root
git add backend/app/core/security.py backend/app/services/provisioning.py backend/tests/conftest.py backend/tests/test_security_argon2_guard.py
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "STOP: git add failed" }
$staged = git diff --cached --name-only
if ($staged) {
    git commit -m "4A-bis: template DB clone fast path, weak argon2 in test env, fast/slow markers"
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "STOP: git commit failed" }
} else {
    Write-Host "Nothing to commit (already patched)."
}
git log --oneline -3
Pop-Location

Write-Host ""
Write-Host "ALL DONE. See 4a_bis.out for the summary block."
# END OF FILE
