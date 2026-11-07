"""One-shot safe fix for the subscriber tenant_schema_version corruption.

Steps:
1. Back up payroll_control with pg_dump.
2. Read: current subscriber value, DB alembic_version, code head.
3. If subscriber > code head  -> UPDATE subscriber DOWN to code head.
   If subscriber < code head  -> ABORT (real migration needed, human decision).
   If subscriber == code head -> print 'already correct' and no-op.
4. Re-read to verify.

Refuses to touch tenant_tenant_demo (its schema is fine).
No migration runs. No control DB migration. No tenant data touched.
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
SLUG = "tenant-demo"
TENANT_DB = "tenant_tenant_demo"
CONTROL_DB = "payroll_control"
ADMIN_USER = "payroll_test"
ADMIN_PW = "payroll_test_dev_password"
CONTROL_URL = (
    f"postgresql+psycopg://{ADMIN_USER}:{ADMIN_PW}@localhost:5432/{CONTROL_DB}"
)
TENANT_URL = (
    f"postgresql+psycopg://{ADMIN_USER}:{ADMIN_PW}@localhost:5432/{TENANT_DB}"
)


def step(title):
    print(f"\n{'=' * 55}\n{title}\n{'=' * 55}")


# ------------------------------------------------------------------
# 1. Backup
# ------------------------------------------------------------------
step("1. Backup payroll_control")
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_path = BACKUP_DIR / f"payroll_control_pre_fix_{stamp}.dump"
env = os.environ.copy()
env["PGPASSWORD"] = ADMIN_PW
r = subprocess.run(
    [PG_DUMP, "-h", "localhost", "-p", "5432", "-U", ADMIN_USER,
     "-F", "c", "-f", str(backup_path), CONTROL_DB],
    env=env, capture_output=True, text=True,
)
if r.returncode != 0:
    print(f"pg_dump FAILED rc={r.returncode}")
    print(r.stderr)
    sys.exit(1)
print(f"backup written: {backup_path} ({backup_path.stat().st_size} bytes)")

# ------------------------------------------------------------------
# 2. Read current state
# ------------------------------------------------------------------
step("2. Read current state")
from sqlalchemy import create_engine, text

# subscriber
eng = create_engine(CONTROL_URL, isolation_level="AUTOCOMMIT")
with eng.connect() as c:
    sub_val = c.execute(
        text("SELECT tenant_schema_version FROM subscriber WHERE slug = :s"),
        {"s": SLUG},
    ).scalar()
eng.dispose()
print(f"subscriber[{SLUG}].tenant_schema_version = {sub_val!r}")

# DB alembic version
eng = create_engine(TENANT_URL, isolation_level="AUTOCOMMIT")
with eng.connect() as c:
    db_val = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
eng.dispose()
print(f"DB[{TENANT_DB}].alembic_version = {db_val!r}")

# code head
os.chdir(BE)
from alembic.config import Config
from alembic.script import ScriptDirectory

cfg = Config("alembic.ini", ini_section="tenant")
sd = ScriptDirectory.from_config(cfg)
heads = sd.get_heads()
code_head = heads[0] if heads else None
print(f"CODE head = {code_head!r} (all heads: {heads})")

# ------------------------------------------------------------------
# 3. Decide and act
# ------------------------------------------------------------------
step("3. Decide")


def _num(v: str | None) -> int | None:
    if v is None:
        return None
    try:
        return int(v.replace("ten_", "").lstrip("0") or "0")
    except Exception:
        return None


sub_n = _num(sub_val)
head_n = _num(code_head)
db_n = _num(db_val)

print(f"subscriber_num={sub_n}  code_head_num={head_n}  db_num={db_n}")

if sub_val is None or code_head is None:
    print("ABORT: missing subscriber row or code head")
    sys.exit(1)

if sub_val == code_head:
    print(f"Already correct: subscriber == code head ({code_head}). No update needed.")
    print("If login still fails, the backend has cached the old value — restart uvicorn.")
    sys.exit(0)

if sub_n is None or head_n is None:
    print("ABORT: cannot parse versions to compare")
    sys.exit(1)

if sub_n < head_n:
    print(
        f"ABORT: subscriber ({sub_val}) is BEHIND code head ({code_head}). "
        f"This is a real migration case. Do not auto-update. "
        f"Stop and consult with the advisor before proceeding."
    )
    sys.exit(1)

if sub_n > head_n:
    print(
        f"FIX NEEDED: subscriber ({sub_val}) is AHEAD of code head ({code_head}). "
        f"Updating subscriber DOWN to {code_head}."
    )
    eng = create_engine(CONTROL_URL, isolation_level="AUTOCOMMIT")
    with eng.begin() as c:
        result = c.execute(
            text(
                "UPDATE subscriber "
                "SET tenant_schema_version = :new, updated_at = NOW() "
                "WHERE slug = :slug AND tenant_schema_version = :old"
            ),
            {"new": code_head, "slug": SLUG, "old": sub_val},
        )
        print(f"  rows updated: {result.rowcount}")
    eng.dispose()
    # Re-read
    step("4. Verify")
    eng = create_engine(CONTROL_URL, isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        new_val = c.execute(
            text("SELECT tenant_schema_version FROM subscriber WHERE slug = :s"),
            {"s": SLUG},
        ).scalar()
    eng.dispose()
    print(f"subscriber[{SLUG}].tenant_schema_version = {new_val!r}")
    if new_val == code_head:
        print("OK — subscriber matches code head. Restart uvicorn and retest login.")
    else:
        print("WARN — update did not stick; investigate before retrying.")
else:
    print("Unknown state — nothing done.")

print("\nDone.")