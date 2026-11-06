"""Phase 1A pre-flight. Read-only. Prints exactly what's needed to write
the migration, permissions, service, API and frontend bundle safely."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BE = ROOT / "backend"
FE = ROOT / "frontend"


def run(cmd, cwd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=cwd, shell=True, timeout=30)
        return r.stdout.strip() or r.stderr.strip()
    except Exception as e:
        return f"ERR: {e}"


def head(path, n=50):
    p = Path(path)
    if not p.exists():
        print(f"--- {path} --- NOT FOUND")
        return
    lines = p.read_text(encoding="utf-8").split("\n")
    print(f"--- {path} ({len(lines)} lines, first {n}) ---")
    for ln in lines[:n]:
        print(ln)
    print()


# 1. GIT
print("=== GIT ===")
print("branch:", run("git rev-parse --abbrev-ref HEAD", ROOT))
print("head:", run("git rev-parse --short HEAD", ROOT))
print("commits:", run("git log --oneline -3", ROOT))
print("dirty:", run("git status --short", ROOT) or "(clean)")

# 2. TENANT MIGRATION HEAD
print("\n=== TENANT MIGRATION HEAD ===")
vdir = BE / "alembic" / "tenant" / "versions"
nums = []
for f in vdir.glob("*.py"):
    m = re.search(r"ten_(\d{4})", f.name)
    if m:
        nums.append((int(m.group(1)), f.name))
nums.sort()
print(f"files: {len(nums)}   highest: {nums[-1] if nums else 'none'}")
print(f"latest 3: {nums[-3:] if len(nums) >= 3 else nums}")

# 3. INTELLIGENCE FILES (should be NONE)
print("\n=== INTELLIGENCE FILES (should be NONE) ===")
found = False
for f in BE.rglob("*intelligence*"):
    print(f"  BE EXISTS: {f.relative_to(BE)}"); found = True
for f in FE.rglob("*intelligence*"):
    print(f"  FE EXISTS: {f.relative_to(FE)}"); found = True
if not found:
    print("  (none — safe to create)")

# 4. permissions.py
print("\n=== permissions.py ===")
perm = BE / "app" / "core" / "permissions.py"
head(perm, n=90)

# 5. errors.py
print("\n=== errors.py ===")
head(BE / "app" / "core" / "errors.py", n=35)

# 6. api/v1/__init__.py
print("\n=== api/v1/__init__.py ===")
head(BE / "app" / "api" / "v1" / "__init__.py", n=70)

# 7. audit write_audit signature
print("\n=== write_audit signature ===")
audit = BE / "app" / "services" / "audit.py"
if audit.exists():
    src = audit.read_text(encoding="utf-8")
    m = re.search(r"def write_audit\([^)]*\)[^:]*:", src, re.DOTALL)
    print(m.group(0)[:600] if m else "(write_audit not found in audit.py)")
else:
    print("audit.py NOT FOUND")

# 8. model conventions — pay.py head
print("\n=== pay.py (enum + TimestampMixin + uuid_pk conventions) ===")
head(BE / "app" / "db" / "tenant" / "models" / "pay.py", n=45)

# 9. tenant model __init__ (what gets imported)
print("\n=== tenant models __init__.py ===")
head(BE / "app" / "db" / "tenant" / "models" / "__init__.py", n=40)

# 10. SetupLayout (for adding Intelligence tab)
print("\n=== SetupLayout.tsx ===")
head(FE / "src" / "pages" / "setup" / "SetupLayout.tsx", n=45)

# 11. strings.ts top-level keys only (fast shape check)
print("\n=== strings.ts top-level keys ===")
st = FE / "src" / "lib" / "strings.ts"
if st.exists():
    for m in re.finditer(r"^  ([a-z][a-zA-Z]*):\s*[\{|\"]", st.read_text(encoding="utf-8"), re.M):
        print(f"  {m.group(1)}")