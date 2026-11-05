"""Job B — read exact bodies needed to add ?as_of=."""
import inspect
from pathlib import Path

from app.services import payroll_runner as pr

for fn_name in ("_build_attendance_earnings", "_build_all_earnings"):
    fn = getattr(pr, fn_name, None)
    print(f"=== {fn_name} ===")
    print(inspect.getsource(fn) if fn else "NOT FOUND")
    print()

print("=== GET /preview/{employee_id} handler (40 lines around) ===")
psrc = Path("app/api/v1/payroll_pay_periods.py").read_text()
lines = psrc.split("\n")
start = None
for i, line in enumerate(lines):
    if "preview/{employee_id}" in line and '"/preview' in line:
        start = i
        break
if start is None:
    print("HANDLER NOT FOUND")
else:
    for j in range(max(0, start - 2), min(len(lines), start + 60)):
        print(f"{j+1:4}: {lines[j]}")

print("\n=== PreviewEmployeeOut model ===")
ssrc = Path("app/api/v1/payroll_pay_periods_schemas.py").read_text()
slines = ssrc.split("\n")
start = None
for i, line in enumerate(slines):
    if "class PreviewEmployeeOut" in line:
        start = i
        break
if start is not None:
    for j in range(start, min(len(slines), start + 40)):
        if j > start and slines[j].startswith("class "):
            break
        print(f"{j+1:4}: {slines[j]}")
else:
    print("SCHEMA NOT FOUND")