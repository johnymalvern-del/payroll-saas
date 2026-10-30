$ErrorActionPreference = 'Stop'
$root = 'C:\xampp\htdocs\Payroll'
$backend = Join-Path $root 'backend'
$pyFile = Join-Path $root '_diag_009.py'

$py = @"
"""One-shot diagnostic for drift + speedup."""
import os, pathlib, sys, uuid, time, subprocess

ROOT = pathlib.Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

print("=" * 60)
print("BUNDLE 009 DIAGNOSTIC")
print("=" * 60)

print()
print("[1] CONFTEST FILES")
for p in BACKEND.rglob("conftest.py"):
    print(f"  {p.relative_to(BACKEND)} ({p.stat().st_size}B)")

print()
print("[2] FULL DRIFT TEST MESSAGE")
r = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_schema_drift.py", "-x", "-vv", "--tb=long", "--no-header"],
    cwd=str(BACKEND), capture_output=True, text=True,
)
print(f"  exit={r.returncode}")
for line in r.stdout.splitlines():
    if "schema drift:" in line or "expected_only" in line or "db_only" in line:
        print(f"  {line}")

print()
print("[3] EMPLOYEE MODEL COLUMNS")
from app.db.tenant.models.people import Employee
model_cols = sorted(c.name for c in Employee.__table__.columns)
print(f"  count: {len(model_cols)}")
print(f"  {model_cols}")

print()
print("[4] FRESH TENANT DB COLUMNS")
from app.core.security import hash_password
from app.services.provisioning import provision_tenant, _tenant_db_name, _drop_tenant_database
from app.db.tenant.session import get_tenant_engine
from sqlalchemy import text

slug = f"diag-{uuid.uuid4().hex[:8]}"
try:
    provision_tenant(slug=slug, name="D", admin_username="admin", admin_password_hash=hash_password("x"))
    db = _tenant_db_name(slug)
    eng = get_tenant_engine(db)
    with eng.connect() as c:
        db_cols = sorted(r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='employee'"
        )))
        ver = c.scalar(text("SELECT version_num FROM alembic_version"))
    eng.dispose()
    print(f"  version: {ver}")
    print(f"  count: {len(db_cols)}")
    print(f"  {db_cols}")
    print(f"  expected_only (model - db): {sorted(set(model_cols) - set(db_cols))}")
    print(f"  db_only (db - model): {sorted(set(db_cols) - set(model_cols))}")
    _drop_tenant_database(db)
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")

print()
print("[5] SPEEDUP STATE")
os.environ["PAYROLL_TEST_TEMPLATE_DB"] = "1"
from app.services import provisioning as p
print(f"  before enable: _TEST_TEMPLATE_ENABLED={p._TEST_TEMPLATE_ENABLED}")
print(f"  before enable: _run_tenant_migrations={p._run_tenant_migrations.__name__}")
print(f"  template name: {p._4a_get_template_name()}")
p._TEST_TEMPLATE_ENABLED = True
p._run_tenant_migrations = p._4a_run_migrations_from_template
print(f"  after enable: _run_tenant_migrations={p._run_tenant_migrations.__name__}")

slug = f"fast-{uuid.uuid4().hex[:8]}"
t0 = time.time()
provision_tenant(slug=slug, name="F", admin_username="admin", admin_password_hash=hash_password("x"))
print(f"  fast provision_tenant: {time.time()-t0:.2f}s")
_drop_tenant_database(_tenant_db_name(slug))

print()
print("[6] CALL TRACKING (is fast path really invoked?)")
calls = []
orig = p._4a_run_migrations_from_template
def track(db_name):
    calls.append(db_name)
    return orig(db_name)
p._run_tenant_migrations = track
slug = f"trk-{uuid.uuid4().hex[:8]}"
provision_tenant(slug=slug, name="T", admin_username="admin", admin_password_hash=hash_password("x"))
_drop_tenant_database(_tenant_db_name(slug))
print(f"  fast path called: {len(calls)} times")

print()
print("DONE.")
"@

[System.IO.File]::WriteAllText($pyFile, $py, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "wrote temp: $pyFile ($((Get-Item $pyFile).Length) bytes)"
cd $root
python $pyFile 2>&1 | Tee-Object -FilePath (Join-Path $root 'diag_009.out')
$rc = $LASTEXITCODE
Write-Host ""
Write-Host "python exit: $rc"
Write-Host "output: diag_009.out"
Remove-Item $pyFile -Force -ErrorAction SilentlyContinue
Start-Process notepad -ArgumentList (Join-Path $root 'diag_009.out')
# END OF FILE
