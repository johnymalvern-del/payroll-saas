$ErrorActionPreference = 'Stop'
$root = 'C:\xampp\htdocs\Payroll'
$backend = Join-Path $root 'backend'

function Parse-Passed([object[]]$lines) {
    $txt = ($lines | Out-String)
    if ($txt -match '(\d+) passed') { return [int]$matches[1] }
    return 0
}

Write-Host "=== step 1: revert people.py + conftest.py to HEAD ==="
Push-Location $root
git checkout HEAD -- backend/app/db/tenant/models/people.py backend/tests/conftest.py
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { throw "STOP: git checkout failed (exit $rc)" }
Write-Host "reverted"

Write-Host ""
Write-Host "=== step 2: reapply v1 patch (security, provisioning, conftest) ==="
Push-Location $root
python scripts\4a_bis_patch.py
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { throw "STOP: v1 patch failed" }

Write-Host ""
Write-Host "=== step 3: reapply v3 (security, idempotent) ==="
Push-Location $root
python scripts\4a_bis_patch_v3.py
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { throw "STOP: v3 patch failed" }

Write-Host ""
Write-Host "=== step 4: byte-safe patch people.py + conftest.py (patch_010b) ==="
Push-Location $root
python scripts\patch_010b.py
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { throw "STOP: patch_010b failed" }

Write-Host ""
Write-Host "=== step 5: verify every patched file ast-parses ==="
Push-Location $backend
foreach ($f in @(
    'app/core/security.py',
    'app/services/provisioning.py',
    'app/db/tenant/models/people.py',
    'tests/conftest.py'
)) {
    python -c "import ast; ast.parse(open('$f', encoding='utf-8').read()); print('ast OK: $f')"
    $rc = $LASTEXITCODE
    if ($rc -ne 0) { throw "STOP: ast failed on $f" }
}

Write-Host ""
Write-Host "=== step 6: verify imports ==="
python -c "from app.db.tenant.models.people import Employee; print('people import OK')"
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "STOP: people import failed" }
python -c "from app.services import provisioning; print('provisioning import OK')"
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "STOP: provisioning import failed" }
python -c "from app.core import security; print('security import OK')"
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "STOP: security import failed" }
python -c "import tests.conftest; print('conftest import OK')"
$rc = $LASTEXITCODE
if ($rc -ne 0) {
    Write-Host "WARN: conftest import test failed (this is normal if it imports pytest-only fixtures)"
}

Write-Host ""
Write-Host "=== step 7: drift test (must pass) ==="
Remove-Item Env:PAYROLL_TEST_TEMPLATE_DB -ErrorAction SilentlyContinue
Remove-Item Env:PAYROLL_TEST_FAST_HASH -ErrorAction SilentlyContinue
$driftOut = python -m pytest tests/test_schema_drift.py -q --no-header 2>&1
$driftExit = $LASTEXITCODE
$driftOut | Select-Object -Last 5 | ForEach-Object { Write-Host $_ }
if ($driftExit -ne 0) { throw "STOP: drift test still fails - see above" }
Pop-Location

Write-Host ""
Write-Host "=== step 8: BEFORE (env unset) ==="
Push-Location $backend
$swb = [System.Diagnostics.Stopwatch]::StartNew()
$beforeOut = python -m pytest tests/test_adjustments.py tests/test_sheet.py -q --no-header 2>&1
$beforeExit = $LASTEXITCODE
$swb.Stop()
Pop-Location
$beforeSec = [int]$swb.Elapsed.TotalSeconds
$beforeCount = Parse-Passed $beforeOut
Write-Host "BEFORE: ${beforeSec}s; passed: $beforeCount; exit: $beforeExit"

Write-Host ""
Write-Host "=== step 9: AFTER #1 (bootstrap) ==="
Push-Location $backend
$env:PAYROLL_TEST_TEMPLATE_DB = '1'
$env:PAYROLL_TEST_FAST_HASH = '1'
$swa1 = [System.Diagnostics.Stopwatch]::StartNew()
$after1Out = python -m pytest tests/test_adjustments.py tests/test_sheet.py tests/test_fastpath_diagnostic.py -q --no-header 2>&1
$after1Exit = $LASTEXITCODE
$swa1.Stop()
Pop-Location
$after1Sec = [int]$swa1.Elapsed.TotalSeconds
$after1Count = Parse-Passed $after1Out
Write-Host "AFTER #1: ${after1Sec}s; passed: $after1Count; exit: $after1Exit"
if ($after1Exit -ne 0) {
    Write-Host "--- AFTER #1 FAILURE TAIL ---"
    $after1Out | Select-Object -Last 40 | ForEach-Object { Write-Host $_ }
}

Write-Host ""
Write-Host "=== step 10: AFTER #2 (steady) ==="
Push-Location $backend
$swa2 = [System.Diagnostics.Stopwatch]::StartNew()
$after2Out = python -m pytest tests/test_adjustments.py tests/test_sheet.py tests/test_fastpath_diagnostic.py -q --no-header 2>&1
$after2Exit = $LASTEXITCODE
$swa2.Stop()
Pop-Location
$after2Sec = [int]$swa2.Elapsed.TotalSeconds
$after2Count = Parse-Passed $after2Out
Write-Host "AFTER #2: ${after2Sec}s; passed: $after2Count; exit: $after2Exit"

Write-Host ""
Write-Host "=== step 11: SUMMARY ==="
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
Write-Host "=== step 12: commit tracked files ==="
Push-Location $root
git add backend/app/db/tenant/models/people.py backend/tests/conftest.py backend/tests/test_fastpath_diagnostic.py scripts/4a_bis_measure.ps1
$rc = $LASTEXITCODE
if ($rc -ne 0) { Write-Host "git add exit: $rc (some files may be gitignored, continuing)" }
$staged = git diff --cached --name-only
if ($staged) {
    git commit -m "4A-bis v4: byte-safe patch (fixes CRLF corruption + drift)"
    Write-Host "commit exit: $LASTEXITCODE"
}
git log --oneline -3
Pop-Location

Write-Host ""
Write-Host "============= PASTE THIS BLOCK BACK ============="
Write-Host "DRIFT: exit=$driftExit"
$driftOut | Select-Object -Last 3 | ForEach-Object { Write-Host "  $_" }
Write-Host ""
Write-Host "SUMMARY:"
Write-Host "  BEFORE: ${beforeSec}s ($beforeCount passed, exit $beforeExit)"
Write-Host "  AFTER #1: ${after1Sec}s ($after1Count passed, exit $after1Exit)"
Write-Host "  AFTER #2: ${after2Sec}s ($after2Count passed, exit $after2Exit)"
if ($estFull -gt 0) {
    Write-Host ("  Estimated full: ${estFull}s (~$([int]($estFull/60)) min)")
}
if ($after1Exit -ne 0) {
    Write-Host ""
    Write-Host "AFTER #1 FAILURE TAIL:"
    $after1Out | Select-Object -Last 20 | ForEach-Object { Write-Host "  $_" }
}
Write-Host "============= END PASTE ============="
Write-Host ""
Write-Host "ALL DONE."
# END OF FILE
