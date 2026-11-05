"""L2d fix: purge scope + seed_demo self-heal.

Root cause of 10 seed_demo errors after patch_conftest_stale_cleanup:
  _purge_stale_test_dbs dropped `tenant_demo%` and `tenant-demo` DBs but
  left matching Subscriber rows in the control DB. Next seed_demo run's
  demo_seed.main() saw "subscriber exists" -> took the keep/reset branch
  -> but tenant DB had been dropped -> OperationalError in migration or
  provisioning.

Fix:
  1. Narrow purge to `payroll_test_%` only. Every other test DB
     (`tenant-demo*`) is managed by seed_demo's own tenant_demo_seeded
     fixture, which drops both the DB and the Subscriber row in teardown.
  2. Add defensive _drop_tenant(slug) at start of tenant_demo_seeded so
     a prior crashed run that skipped teardown is healed before seeding.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONF = ROOT / "backend" / "tests" / "conftest.py"
SEED = ROOT / "backend" / "tests" / "test_seed_demo.py"

# ---- 1. Narrow the purge pattern ----
src = CONF.read_text(encoding="utf-8")
old_sql = '''            rows = conn.execute(text(
                "SELECT datname FROM pg_database "
                "WHERE datname LIKE 'payroll_test_%' "
                "   OR datname = 'tenant-demo' "
                "   OR datname LIKE 'tenant_demo%' "
                "   OR datname LIKE 'tenant-test-%' "
                "   OR datname LIKE 'tenant_test_%'"
            )).fetchall()'''
new_sql = '''            rows = conn.execute(text(
                "SELECT datname FROM pg_database "
                "WHERE datname LIKE 'payroll_test_%'"
            )).fetchall()'''
if old_sql in src:
    src = src.replace(old_sql, new_sql, 1)
    print("conftest: purge narrowed to payroll_test_% only")
elif new_sql in src:
    print("conftest: purge already narrowed")
else:
    raise SystemExit("FATAL: purge SQL not found (conftest shape changed)")
CONF.write_text(src, encoding="utf-8")

# ---- 2. Self-heal seed_demo fixture ----
s = SEED.read_text(encoding="utf-8")
old_fix = '''@pytest.fixture(scope="session")
def tenant_demo_seeded() -> Iterator[str]:
    rc = _seed(_SESSION_SLUG, ["--reset"])
    try:
        yield _SESSION_SLUG
    finally:
        _drop_tenant(_SESSION_SLUG)
'''
new_fix = '''@pytest.fixture(scope="session")
def tenant_demo_seeded() -> Iterator[str]:
    _drop_tenant(_SESSION_SLUG)  # self-heal from prior crashed run
    rc = _seed(_SESSION_SLUG, ["--reset"])
    try:
        yield _SESSION_SLUG
    finally:
        _drop_tenant(_SESSION_SLUG)
'''
if old_fix in s:
    s = s.replace(old_fix, new_fix, 1)
    print("test_seed_demo: _drop_tenant at start of tenant_demo_seeded")
elif new_fix in s:
    print("test_seed_demo: self-heal already present")
else:
    raise SystemExit("FATAL: tenant_demo_seeded shape not found")
SEED.write_text(s, encoding="utf-8")
print("WROTE conftest.py + test_seed_demo.py")