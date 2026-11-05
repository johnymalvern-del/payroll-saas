"""Probe for Job B (payslip-so-far backend as_of). Prints:
1. All preview paths + request params + response schema
2. Preview response field names
3. Permission.PAYROLL_PREVIEW and role grants
4. run_preview signature (does it take a cutoff/as_of today?)
5. Whether preview persists rows
6. cutoff / as_of / end_date / today usage in payroll_pay_periods.py
7. Employee pay_basis / employee_type / pay_frequency enum values
8. PayrollSettings fields for unpaid / monthly / holiday / attendance_earning
9. Sample run_preview preview response for one employee on the demo tenant
"""
import inspect, json, re
from pathlib import Path

from app.main import app
from app.core.permissions import Permission
from app.services.payroll_runner import run_preview

s = app.openapi()
comps = s.get("components", {}).get("schemas", {})
paths = s.get("paths", {})

print("=== 1. preview paths ===")
for p in sorted(paths):
    if "preview" in p.lower():
        print(f"  {p}")
        for m, op in paths[p].items():
            if m not in ("get", "post"):
                continue
            print(f"    {m.upper()}")
            for param in op.get("parameters", []):
                req = param.get("required", False)
                sch = param.get("schema", {})
                print(f"      {param['in']:6} {param['name']:20} required={req} {json.dumps(sch)[:80]}")
            rb = op.get("requestBody", {})
            if rb:
                print(f"      body: {json.dumps(rb)[:300]}")

print("\n=== 2. preview response schema field names ===")
for n in sorted(comps):
    if "preview" in n.lower():
        props = list(comps[n].get("properties", {}).keys())
        print(f"  {n}: {props}")

print("\n=== 3. Permission.PAYROLL_PREVIEW + role grants ===")
print(f"  enum value: {Permission.PAYROLL_PREVIEW}")
from app.core import permissions as perm_mod
for attr in dir(perm_mod):
    obj = getattr(perm_mod, attr)
    if isinstance(obj, dict):
        for role, perms in obj.items():
            if isinstance(perms, (list, set, tuple, frozenset)):
                if any(p == Permission.PAYROLL_PREVIEW for p in perms):
                    print(f"  {attr}[{role}] grants PAYROLL_PREVIEW")

print("\n=== 4. run_preview signature ===")
print(f"  run_preview{inspect.signature(run_preview)}")

print("\n=== 5. preview persistence in payroll_runner.py ===")
src = Path("app/services/payroll_runner.py").read_text()
for line_no, line in enumerate(src.split("\n"), 1):
    if "preview_row" in line.lower() or ("preview" in line.lower() and "persist" in line.lower()):
        print(f"  L{line_no}: {line.strip()[:160]}")

print("\n=== 6. cutoff / as_of / end_date / today usage in payroll_pay_periods.py ===")
psrc = Path("app/api/v1/payroll_pay_periods.py").read_text()
for line_no, line in enumerate(psrc.split("\n"), 1):
    if re.search(r"cutoff|as_of|end_date|today", line, re.I):
        print(f"  L{line_no}: {line.strip()[:160]}")

print("\n=== 7. Employee enums ===")
emp = comps.get("EmployeeOut", {})
for k in ("pay_basis", "employee_type", "pay_frequency"):
    if k in emp.get("properties", {}):
        print(f"  EmployeeOut.{k}: {json.dumps(emp['properties'][k])[:200]}")

print("\n=== 8. PayrollSettings relevant fields ===")
for n in sorted(comps):
    if "PayrollSettings" in n:
        props = comps[n].get("properties", {})
        for k in props:
            if any(x in k.lower() for x in ("unpaid", "monthly", "holiday", "attendance_earning", "demo")):
                print(f"  {n}.{k}: {json.dumps(props[k])[:120]}")