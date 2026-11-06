"""Print the current state of the preview handler + helper so I can see
what the line-based patches actually landed."""
from pathlib import Path
import re

P = Path(__file__).resolve().parent.parent / "backend" / "app" / "api" / "v1" / "payroll_pay_periods.py"
lines = P.read_text(encoding="utf-8").split("\n")
print(f"=== payroll_pay_periods.py ({len(lines)} lines) ===")

# 1. helper present?
print("\n=== _preview_as_of present? ===")
for i, ln in enumerate(lines, 1):
    if "def _preview_as_of" in ln:
        print(f"  FOUND at line {i}: {ln.strip()}")
        # print 25 lines of it
        for j in range(i - 1, min(i + 25, len(lines))):
            print(f"  {j+1:4}: {lines[j]}")
        break
else:
    print("  NOT FOUND")

# 2. route handler current state
print("\n=== preview_employee route handler ===")
for i, ln in enumerate(lines, 1):
    if '@router.get("/{period_id}/preview/{employee_id}"' in ln:
        for j in range(i - 1, min(i + 50, len(lines))):
            print(f"  {j+1:4}: {lines[j]}")
        break
else:
    print("  route decorator not found")

# 3. imports present?
print("\n=== imports check ===")
for token in ("from app.core.scope import", "from app.services.payroll_runner import",
              "from app.db.tenant.models.pay import",
              "from app.db.tenant.models.people import", "from datetime import date"):
    for i, ln in enumerate(lines, 1):
        if ln.startswith(token):
            print(f"  L{i}: {ln}")
            break
    else:
        print(f"  MISSING: {token}")