"""L2d fix: purge stale test DBs at session start + NullPool on session engines.

Root cause of the 10 seed_demo errors, 368 full-suite errors, and the 1 error
in audit_log / pdf_demo:
  - A crashed pytest run leaves tenant DBs (payroll_test_*, tenant-demo, etc.)
    alive in Postgres plus orphan backends.
  - The next run's provision_tenant / seed_demo tries to CREATE SCHEMA where
    schema already exists -> OperationalError / ProgrammingError.
  - Session-scoped engines (tenant_engine_admin/app) with QueuePool hold
    connections open across a 52-min run. NullPool + explicit teardown keeps
    connection count bounded.

Fix:
  - New autouse session fixture `_purge_stale_test_dbs` that runs BEFORE
    `_control_test_database` and drops every leftover test DB (terminating
    its backends first).
  - Tenant session engines switch to `poolclass=NullPool` so each .connect()
    opens a fresh OS connection and .close() really closes it.
"""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "backend" / "tests" / "conftest.py"
src = P.read_text(encoding="utf-8")

# ---- 1. NullPool import + application ----
if "NullPool" not in src:
    anchor = "from sqlalchemy.engine import Engine\n"
    if anchor not in src:
        raise SystemExit("FATAL: Engine import anchor missing")
    src = src.replace(
        anchor,
        anchor + "from sqlalchemy.pool import NullPool\n",
        1,
    )
    print("conftest: NullPool import added")
else:
    print("conftest: NullPool import already present")

# apply to both tenant session engines
old_eng = 'engine = create_engine(url, future=True)\n    try:\n        yield engine\n'
new_eng = 'engine = create_engine(url, future=True, poolclass=NullPool)\n    try:\n        yield engine\n'
n = src.count(old_eng)
if n == 2:
    src = src.replace(old_eng, new_eng)
    print("conftest: NullPool applied to both tenant session engines")
elif n == 0:
    print("conftest: tenant engines already NullPool (or different shape)")
else:
    raise SystemExit(f"FATAL: expected 2 tenant engines, found {n}")

# ---- 2. Session-start purge fixture ----
if "def _purge_stale_test_dbs():" not in src:
    anchor = '@pytest.fixture(scope="session", autouse=True)\ndef _control_test_database()'
    if anchor not in src:
        raise SystemExit("FATAL: _control_test_database anchor missing")
    purge = '''@pytest.fixture(scope="session", autouse=True)
def _purge_stale_test_dbs() -> Iterator[None]:
    """Drop leftover test DBs + orphan backends before any test runs.

    A crashed prior pytest run can leave payroll_test_* / tenant-demo /
    tenant_demo* / tenant-test-* / tenant_test_* alive. Next run's
    provision_tenant / seed_demo then errors with schema-exists or
    connection-slot exhaustion.
    """
    engine = create_engine(
        _admin_url("postgres"), isolation_level="AUTOCOMMIT", future=True,
    )
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT datname FROM pg_database "
                "WHERE datname LIKE 'payroll_test_%' "
                "   OR datname = 'tenant-demo' "
                "   OR datname LIKE 'tenant_demo%' "
                "   OR datname LIKE 'tenant-test-%' "
                "   OR datname LIKE 'tenant_test_%'"
            )).fetchall()
            for (name,) in rows:
                conn.execute(text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :d AND pid <> pg_backend_pid()"
                ), {"d": name})
                conn.execute(text(f\'DROP DATABASE IF EXISTS "{name}"\'))
                print(f"purged stale test DB: {name}")
    finally:
        engine.dispose()
    yield


'''
    src = src.replace(anchor, purge + anchor, 1)
    print("conftest: _purge_stale_test_dbs fixture added")
else:
    print("conftest: _purge_stale_test_dbs already present")

P.write_text(src, encoding="utf-8")
print("WROTE conftest.py")