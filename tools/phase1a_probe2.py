"""Phase 1A probe #2 — locates migrations, write_audit, AuditLog model.
Read-only, filesystem only."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BE = ROOT / "backend"


def run(cmd, cwd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=cwd, shell=True, timeout=20)
        return (r.stdout or r.stderr).strip()
    except Exception as e:
        return f"ERR: {e}"


# 1. Locate every .py under backend/alembic
print("=== backend/alembic tree ===")
for p in sorted(BE.rglob("alembic/**/*")):
    if p.is_file():
        print(f"  {p.relative_to(BE)}")

print("\n=== candidate migration directories with .py files ===")
for d in BE.rglob("*versions*"):
    if d.is_dir():
        n = len(list(d.glob("*.py")))
        if n:
            print(f"  {d.relative_to(BE)}  ({n} .py files)")

print("\n=== alembic.ini ===")
ini = BE / "alembic.ini"
if ini.exists():
    for ln in ini.read_text(encoding="utf-8").split("\n"):
        if "script_location" in ln or "version_locations" in ln:
            print(f"  {ln.strip()}")

print("\n=== alembic env.py sections (head) ===")
for envpy in BE.rglob("alembic/**/env.py"):
    print(f"--- {envpy.relative_to(BE)} (first 35) ---")
    for ln in envpy.read_text(encoding="utf-8").split("\n")[:35]:
        print(f"  {ln}")

# 2. Where is write_audit defined?
print("\n=== write_audit definition ===")
print(run(
    'findstr /S /N /C:"def write_audit" app\\*.py',
    BE,
) or "(findstr found nothing)")

print("\n=== files mentioning write_audit (first 10) ===")
print(run(
    'findstr /S /N /M "write_audit" app\\*.py',
    BE,
)[:1500] or "(none)")

# 3. AuditLog model — full body
print("\n=== AuditLog model (platform.py) ===")
plat = BE / "app" / "db" / "tenant" / "models" / "platform.py"
if plat.exists():
    src = plat.read_text(encoding="utf-8")
    m = re.search(r"class AuditLog\([\s\S]*?(?=\nclass |\Z)", src)
    print(m.group(0) if m else "(AuditLog class not found)")
else:
    print("platform.py NOT FOUND")

# 4. Any other Base subclasses named *Log or *Setting
print("\n=== other models in platform.py ===")
if plat.exists():
    src = plat.read_text(encoding="utf-8")
    for m in re.finditer(r"^class (\w+)\(Base\):", src, re.M):
        print(f"  {m.group(1)}")