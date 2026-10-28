"""2B-1b fix: shifts.py uses AttendanceDay but never imported it.

Finds the `from app.db.tenant.models.attendance import ...` node in
shifts.py (single-line or parenthesised multi-line), adds AttendanceDay to
its names, rewrites the file, and runs the four guard tests. Idempotent:
if AttendanceDay is already in the import names, it reports that and does
not touch the file.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\xampp\htdocs\Payroll")
BACKEND = ROOT / "backend"
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def fail(msg: str) -> None:
    print(f"STOP: {msg}")
    sys.exit(1)


def run(cmd: list) -> int:
    print("$ " + " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=str(BACKEND),
                       capture_output=True, text=True)
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.stderr.strip():
        print("STDERR:", r.stderr.strip())
    return r.returncode


shifts_path = BACKEND / "app" / "api" / "v1" / "shifts.py"
text = shifts_path.read_text(encoding="utf-8")

try:
    tree = ast.parse(text)
except SyntaxError as e:
    fail(f"shifts.py does not parse: {e}")

target = None
for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom) and node.module == "app.db.tenant.models.attendance":
        target = node
        break

if target is None:
    fail("shifts.py has no `from app.db.tenant.models.attendance import ...`")

names = [alias.name for alias in target.names]
print(f"existing attendance import names: {names}")

if "AttendanceDay" in names:
    print("AttendanceDay is already imported; nothing to do")
else:
    all_names = ["AttendanceDay"] + [n for n in names if n != "AttendanceDay"]
    new_line = f'from app.db.tenant.models.attendance import {", ".join(all_names)}'
    lines = text.splitlines()
    start = target.lineno - 1
    end = target.end_lineno  # exclusive
    lines[start:end] = [new_line]
    new_text = "\n".join(lines) + "\n"
    try:
        ast.parse(new_text)
    except SyntaxError as e:
        fail(f"patched shifts.py does not parse: {e}")
    shifts_path.write_text(new_text, encoding="utf-8")
    if shifts_path.read_bytes()[:3] == b"\xef\xbb\xbf":
        fail("shifts.py was written with a BOM")
    print(f"patched shifts.py: import now {all_names}")

# -------------------------------------------------------------------------
# Verify
# -------------------------------------------------------------------------
print("--- verifying ---")

if run([PY, "-c", "from app.main import app; print('import OK')"]) != 0:
    fail("app import")

if run([PY, "-m", "pytest", "tests/test_2b1b_guards.py", "-v"]) != 0:
    fail("guard tests")

print("2B-1b PASS")