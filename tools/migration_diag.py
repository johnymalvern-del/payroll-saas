"""Read-only diagnostic for the tenant-demo migration gap.

Nothing is written. Reads git state, migration chain, tenant registry,
alembic versions in every candidate DB, backup tooling availability,
and the schema-behind check that is blocking login.
"""
import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BE = ROOT / "backend"


def run(cmd, cwd=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=cwd or ROOT, shell=True, timeout=20)
        return (r.stdout or r.stderr).strip()
    except Exception as e:
        return f"ERR: {e}"


def head(path, n=60, marker=None, ctx=0):
    p = Path(path)
    if not p.exists():
        print(f"--- {path} --- NOT FOUND\n")
        return
    lines = p.read_text(encoding="utf-8").split("\n")
    print(f"--- {path} ({len(lines)} lines) ---")
    if marker:
        for i, ln in enumerate(lines):
            if marker in ln:
                lo = max(0, i - ctx)
                hi = min(len(lines), i + n)
                for j in range(lo, hi):
                    print(f"{j+1:4}: {lines[j]}")
                print()
                return
        print(f"  marker {marker!r} not found\n")
        return
    for ln in lines[:n]:
        print(ln)
    print()


# =========================================================
# 1. GIT STATE
# =========================================================
print("=== 1. GIT ===")
print("head:", run("git rev-parse --short HEAD"))
print("branch:", run("git rev-parse --abbrev-ref HEAD"))
print("dirty:", run("git status --short") or "(clean)")
print()

# =========================================================
# 2. MIGRATION CHAIN — 0024 down_revision, 0025 revision/down
# =========================================================
print("=== 2. MIGRATION CHAIN ===")
for fn in ("0024_leave_request_link.py", "0025_intelligence_foundation.py"):
    p = BE / "alembic" / "tenant" / "versions" / fn
    if not p.exists():
        print(f"{fn}: NOT FOUND")
        continue
    txt = p.read_text(encoding="utf-8")
    rev = re.search(r'^revision\s*=\s*"([^"]+)"', txt, re.M)
    dr = re.search(r'^down_revision\s*=\s*"([^"]+)"', txt, re.M)
    print(f"{fn}: revision={rev.group(1) if rev else '?'} "
          f"down_revision={dr.group(1) if dr else '?'}")
print()

# =========================================================
# 3. CONTENT OF 0025 — is it additive only, or does it modify data?
# =========================================================
print("=== 3. 0025 CONTENT SAFETY ===")
m25 = BE / "alembic" / "tenant" / "versions" / "0025_intelligence_foundation.py"
if m25.exists():
    txt = m25.read_text(encoding="utf-8")
    ops_create = re.findall(r"op\.create_table\(", txt)
    ops_drop = re.findall(r"op\.drop_table\(", txt)  # in downgrade, expected
    ops_alter = re.findall(r"op\.(add_column|drop_column|alter_column)\(", txt)
    ops_execute = re.findall(r"op\.execute\(", txt)
    print(f"create_table calls: {len(ops_create)}")
    print(f"drop_table calls (in downgrade): {len(ops_drop)}")
    print(f"alter_column / add_column / drop_column: {len(ops_alter)}")
    print(f"op.execute raw SQL: {len(ops_execute)}")
    if ops_execute:
        for m in re.finditer(r"op\.execute\([^)]*", txt):
            print(f"  exec: {m.group(0)[:120]}")
else:
    print("0025 file not found")
print()

# =========================================================
# 4. TENANT DB NAME RESOLUTION
# =========================================================
print("=== 4. _tenant_db_name IMPLEMENTATION ===")
prov = BE / "app" / "services" / "provisioning.py"
if prov.exists():
    txt = prov.read_text(encoding="utf-8")
    m = re.search(r"def _tenant_db_name\([^)]*\)[^:]*:\n(?:    [^\n]*\n)+", txt)
    if m:
        print(m.group(0))
    m2 = re.search(r"def run_tenant_migrations\([^)]*\)[^:]*:\n(?:    [^\n]*\n)+", txt)
    if m2:
        print(m2.group(0)[:600])
print()

# =========================================================
# 5. SUBSCRIBER ROWS (payroll_control)
# =========================================================
print("=== 5. SUBSCRIBER REGISTRY (payroll_control) ===")
try:
    from sqlalchemy import create_engine, text
    eng = create_engine(
        "postgresql+psycopg://payroll_app:payroll_app_dev_password"
        "@localhost:5432/payroll_control"
    )
    with eng.connect() as c:
        cols = [r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='subscriber'"
        ))]
        print("subscriber columns:", cols)
        print("\nrows:")
        for r in c.execute(text("SELECT * FROM subscriber ORDER BY slug")):
            print(" ", dict(r._mapping))
    eng.dispose()
except Exception as e:
    print("ERR:", e)
print()

# =========================================================
# 6. ALEMBIC VERSION IN EVERY CANDIDATE DEMO DB
# =========================================================
print("=== 6. ALEMBIC VERSION per candidate demo DB ===")
try:
    from sqlalchemy import create_engine, text
    admin = create_engine(
        "postgresql+psycopg://payroll_test:payroll_test_dev_password"
        "@localhost:5432/postgres",
        isolation_level="AUTOCOMMIT",
    )
    with admin.connect() as c:
        names = [r[0] for r in c.execute(text(
            "SELECT datname FROM pg_database "
            "WHERE datname ILIKE '%demo%' OR datname LIKE 'tenant%' "
            "ORDER BY datname"
        ))]
    print("candidate DBs:", names)
    for db in names:
        url = (f"postgresql+psycopg://payroll_test:payroll_test_dev_password"
               f"@localhost:5432/{db}")
        try:
            e2 = create_engine(url, isolation_level="AUTOCOMMIT")
            with e2.connect() as c2:
                ver = c2.execute(text(
                    "SELECT version_num FROM alembic_version"
                )).scalar()
                print(f"  {db}: {ver}")
            e2.dispose()
        except Exception as e:
            print(f"  {db}: ERR {e}")
    admin.dispose()
except Exception as e:
    print("ERR:", e)
print()

# =========================================================
# 7. BACKUP TOOLING AVAILABILITY
# =========================================================
print("=== 7. BACKUP TOOLING ===")
print("pg_dump:", run("where pg_dump") or "(not on PATH)")
print("pg_restore:", run("where pg_restore") or "(not on PATH)")
print("pg_dump --version:", run("pg_dump --version") or "(not available)")
# Check for project backup scripts
for pattern in ("**/*backup*", "scripts/*", "tools/*migrate*"):
    for f in BE.parent.glob(pattern):
        if f.is_file() and f.suffix in (".py", ".ps1", ".bat", ".sh", ".md"):
            print(f"  project file: {f.relative_to(BE.parent)}")
print()

# =========================================================
# 8. SCHEMA-BEHIND CHECK (login block source)
# =========================================================
print("=== 8. SCHEMA-BEHIND / LOGIN BLOCK SOURCE ===")
found = False
for p in BE.rglob("*.py"):
    try:
        txt = p.read_text(encoding="utf-8")
    except Exception:
        continue
    if ("schema_behind" in txt or "requires a migration" in txt
            or "requires_migration" in txt):
        print(f"  {p.relative_to(BE)}")
        found = True
if not found:
    print("  (no matches — might be in a migration env check or doctor module)")

# Any doctor / health check module
for p in BE.rglob("doctor*.py"):
    print(f"  doctor: {p.relative_to(BE)}")
    txt = p.read_text(encoding="utf-8")
    for i, ln in enumerate(txt.split("\n"), 1):
        if "ten_" in ln or "alembic" in ln.lower() or "schema" in ln.lower():
            print(f"    L{i}: {ln.strip()[:140]}")
print()
print("=== END ===")