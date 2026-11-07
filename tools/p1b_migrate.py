"""Phase 1B: backup + migrate tenant_tenant_demo to ten_0026 + verify.

Backup both DBs first. If pg_dump fails, exits before migration.
Upgrade is idempotent — if DB is already at ten_0026, alembic does nothing.
"""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BE = ROOT / "backend"
BACKUP_DIR = ROOT / "backups"
PG_DUMP = r"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe"
TENANT = "tenant_tenant_demo"
CONTROL = "payroll_control"
ADMIN_USER = "payroll_test"
ADMIN_PW = "payroll_test_dev_password"
TENANT_URL = f"postgresql+psycopg://{ADMIN_USER}:{ADMIN_PW}@localhost:5432/{TENANT}"


def step(t):
    print(f"\n{'=' * 55}\n{t}\n{'=' * 55}")


# 1. Backup
step("1. Backup")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
env = os.environ.copy()
env["PGPASSWORD"] = ADMIN_PW
for db in (TENANT, CONTROL):
    path = BACKUP_DIR / f"{db}_p1b_migrate_{stamp}.dump"
    r = subprocess.run(
        [PG_DUMP, "-h", "localhost", "-p", "5432", "-U", ADMIN_USER,
         "-F", "c", "-f", str(path), db],
        env=env, capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"BACKUP FAILED for {db}: {r.stderr.strip()}")
        sys.exit(1)
    print(f"  backup: {path.name} ({path.stat().st_size} bytes)")

# 2. Migrate
step("2. Migrate tenant_tenant_demo")
os.chdir(BE)
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

cfg = Config("alembic.ini", ini_section="tenant")
cfg.set_main_option("sqlalchemy.url", TENANT_URL)
sd = ScriptDirectory.from_config(cfg)
print(f"  code head: {sd.get_heads()}")
command.upgrade(cfg, "head")
print("  upgrade completed")

# 3. Verify
step("3. Verify")
from sqlalchemy import create_engine, text

eng = create_engine(TENANT_URL, isolation_level="AUTOCOMMIT")
with eng.connect() as c:
    ver = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
    print(f"  alembic_version: {ver}")

    tables = [r[0] for r in c.execute(text(
        "SELECT tablename FROM pg_tables WHERE tablename LIKE 'intelligence%' ORDER BY tablename"
    ))]
    print(f"  intelligence tables: {len(tables)}")
    for t in tables:
        print(f"    {t}")

    cols = [r[0] for r in c.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='intelligence_decision' "
        "AND column_name IN ('decision_type','initiator_type','initiator_user_id',"
        "'company_default_mode','effective_workflow_mode','workflow_override_mode',"
        "'idempotency_key','evidence_snapshot_id') ORDER BY column_name"
    ))]
    print(f"  new columns on intelligence_decision: {len(cols)}/8")
    for cc in cols:
        print(f"    {cc}")

    trigs = [r[0] for r in c.execute(text(
        "SELECT tgname FROM pg_trigger "
        "WHERE tgrelid='intelligence_evidence_snapshot'::regclass "
        "AND NOT tgisinternal"
    ))]
    print(f"  triggers on snapshot: {trigs}")
eng.dispose()

print("\n=== MIGRATION COMPLETE ===")
print("Next: restart uvicorn (Ctrl+C in the backend window, then re-run it),")
print("then test login.")