"""Final Phase 1A probe. Prints the 4 shapes I must match:
- write_audit exact signature
- ROLE_PERMISSIONS tail (payroll_admin and hr entries)
- test_permissions.py matrix structure
- Setting model (for JSON-config-style patterns)
"""
from pathlib import Path

BE = Path(__file__).resolve().parent.parent / "backend"


def show(path, from_line=1, to_line=None, marker=None, ctx=0):
    p = Path(path)
    if not p.exists():
        print(f"--- {path} --- NOT FOUND"); return
    lines = p.read_text(encoding="utf-8").split("\n")
    print(f"--- {path} ({len(lines)} lines) ---")
    if marker:
        for i, ln in enumerate(lines):
            if marker in ln:
                lo = max(0, i - ctx)
                hi = min(len(lines), i + 45 + ctx)
                for j in range(lo, hi):
                    print(f"{j+1:4}: {lines[j]}")
                return
        print(f"  (marker {marker!r} not found)")
        return
    hi = to_line if to_line else len(lines)
    for j in range(from_line - 1, min(hi, len(lines))):
        print(f"{j+1:4}: {lines[j]}")


# 1. write_audit
print("=== 1. write_audit ===")
show(BE / "app" / "services" / "payroll_audit.py", marker="def write_audit")

# 2. permissions.py — payroll_admin + hr tails + role-mapping section
print("\n=== 2. permissions.py — role-mapping section ===")
show(BE / "app" / "core" / "permissions.py",
     marker="ROLE_PERMISSIONS", ctx=0)

# 3. test_permissions.py
print("\n=== 3. test_permissions.py — first 90 lines ===")
show(BE / "tests" / "test_permissions.py", from_line=1, to_line=90)

print("\n=== 3b. test_permissions.py — where matrix is redeclared ===")
tp = BE / "tests" / "test_permissions.py"
if tp.exists():
    src = tp.read_text(encoding="utf-8")
    for i, ln in enumerate(src.split("\n"), 1):
        if ("ROLE_PERMISSIONS" in ln or "EXPECTED" in ln
                or "expected" in ln.lower() and "role" in ln.lower()):
            print(f"{i:4}: {ln}")

# 4. Setting model
print("\n=== 4. Setting model (platform.py) ===")
show(BE / "app" / "db" / "tenant" / "models" / "platform.py",
     marker="class Setting")

# 5. In case models/__init__ needs updating
print("\n=== 5. Confirm models/__init__.py does NOT import pay.py ===")
ini = BE / "app" / "db" / "tenant" / "models" / "__init__.py"
if ini.exists():
    print(ini.read_text(encoding="utf-8"))