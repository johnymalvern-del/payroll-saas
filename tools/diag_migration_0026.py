"""Read-only diagnosis: 'Tenant tenant-demo requires migration (ten_0026 -> ten_0025)'.

Reads git, migration files, subscriber row, actual DB alembic_version,
and the schema-check source. No writes, no migration, no commands run
against the DB beyond SELECT.
"""
import os
import re
import subprocess
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


def section(t):
    print(f"\n{'=' * 60}\n{t}\n{'=' * 60}")


# 1. GIT
section("1. GIT STATE")
print("head:", run("git rev-parse --short HEAD"))
print("branch:", run("git rev-parse --abbrev-ref HEAD"))
print("dirty:", run("git status --short") or "(clean)")
print("\nlast 8 commits:")
print(run("git log --oneline -8"))
print("\ncommits since f5eba68 (Phase 1A baseline):")
print(run("git log --oneline f5eba68..HEAD") or "(none — HEAD is f5eba68 or earlier)")

# 2. MIGRATION FILES
section("2. TENANT MIGRATION FILES")
versions = sorted((BE / "alembic" / "tenant" / "versions").glob("*.py"))
print(f"total tenant migration files: {len(versions)}")
print("last 5 files:")
for v in versions[-5:]:
    txt = v.read_text(encoding="utf-8")
    rev = re.search(r'^revision\s*=\s*"([^"]+)"', txt, re.M)
    dr = re.search(r'^down_revision\s*=\s*"([^"]+)"', txt, re.M)
    print(f"  {v.name}: revision={rev.group(1) if rev else '?'} "
          f"down_revision={dr.group(1) if dr else '?'}")

print("\nlook for any 0026 file:")
hits = list((BE / "alembic" / "tenant" / "versions").glob("*0026*"))
if hits:
    for h in hits:
        print(f"  FOUND: {h.name}")
        txt = h.read_text(encoding="utf-8")
        rev = re.search(r'^revision\s*=\s*"([^"]+)"', txt, re.M)
        dr = re.search(r'^down_revision\s*=\s*"([^"]+)"', txt, re.M)
        print(f"    revision={rev.group(1) if rev else '?'} "
              f"down_revision={dr.group(1) if dr else '?'}")
else:
    print("  NONE — no 0026_*.py in the tenant versions dir")

# 3. ALEMBIC HEADS (authoritative)
section("3. ALEMBIC HEADS")
try:
    os.chdir(BE)
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    for section_name in ("tenant", "control"):
        try:
            cfg = Config("alembic.ini", ini_section=section_name)
            sd = ScriptDirectory.from_config(cfg)
            print(f"  {section_name} heads: {sd.get_heads()}")
            print(f"  {section_name} bases: {sd.get_bases()}")
        except Exception as e:
            print(f"  {section_name} ERR: {e}")
except Exception as e:
    print(f"  ERR: {e}")

# 4. SUBSCRIBER ROWS
section("4. SUBSCRIBER ROWS (payroll_control)")
try:
    from sqlalchemy import create_engine, text
    eng = create_engine(
        "postgresql+psycopg://payroll_app:payroll_app_dev_password"
        "@localhost:5432/payroll_control",
        isolation_level="AUTOCOMMIT",
    )
    with eng.connect() as c:
        print("slug | tenant_db_name | tenant_schema_version | status")
        for r in c.execute(text(
            "SELECT slug, tenant_db_name, tenant_schema_version, status "
            "FROM subscriber ORDER BY slug"
        )):
            print(f"  {r[0]} | {r[1]} | {r[2]} | {r[3]}")
    eng.dispose()
except Exception as e:
    print(f"ERR: {e}")

# 5. TENANT_TENANT_DEMO ACTUAL VERSION
section("5. tenant_tenant_demo alembic_version")
try:
    from sqlalchemy import create_engine, text
    eng = create_engine(
        "postgresql+psycopg://payroll_test:payroll_test_dev_password"
        "@localhost:5432/tenant_tenant_demo",
        isolation_level="AUTOCOMMIT",
    )
    with eng.connect() as c:
        v = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
        print(f"  alembic_version: {v}")
    eng.dispose()
except Exception as e:
    print(f"ERR: {e}")

# 6. SCHEMA CHECK SOURCE (where the error is raised)
section("6. SCHEMA CHECK SOURCE (app/api/deps.py)")
p = BE / "app" / "api" / "deps.py"
if p.exists():
    lines = p.read_text(encoding="utf-8").split("\n")
    hit = None
    for i, ln in enumerate(lines):
        if "requires a migration" in ln or "schema_behind" in ln:
            hit = i
            break
    if hit is None:
        print("(no 'requires a migration' / 'schema_behind' found in deps.py)")
    else:
        lo = max(0, hit - 45)
        hi = min(len(lines), hit + 25)
        for j in range(lo, hi):
            marker = ">>" if j == hit else "  "
            print(f"{marker} {j+1:4}: {lines[j]}")
else:
    print(f"NOT FOUND: {p}")

# 7. OTHER TENANT DB VERSIONS (context)
section("7. ALL tenant* DB VERSIONS")
try:
    from sqlalchemy import create_engine, text
    admin = create_engine(
        "postgresql+psycopg://payroll_test:payroll_test_dev_password"
        "@localhost:5432/postgres",
        isolation_level="AUTOCOMMIT",
    )
    with admin.connect() as c:
        names = [r[0] for r in c.execute(text(
            "SELECT datname FROM pg_database WHERE datname LIKE 'tenant%' "
            "ORDER BY datname"
        ))]
    print(f"{len(names)} candidate DBs")
    for db in names:
        try:
            e2 = create_engine(
                f"postgresql+psycopg://payroll_test:payroll_test_dev_password"
                f"@localhost:5432/{db}",
                isolation_level="AUTOCOMMIT",
            )
            with e2.connect() as c2:
                v = c2.execute(text(
                    "SELECT version_num FROM alembic_version"
                )).scalar()
                print(f"  {db}: {v}")
            e2.dispose()
        except Exception as e:
            print(f"  {db}: ERR {str(e)[:60]}")
    admin.dispose()
except Exception as e:
    print(f"ERR: {e}")

print("\n=== END DIAG ===")