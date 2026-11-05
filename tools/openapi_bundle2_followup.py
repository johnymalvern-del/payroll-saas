import json
from app.main import app

s = app.openapi()
comps = s.get("components", {}).get("schemas", {})

print("=== default_shift_id appearances in any schema ===")
found = []
for name, sch in comps.items():
    if "default_shift_id" in json.dumps(sch):
        found.append(name)
        print(f"  {name}")
if not found:
    print("  (none)")

for name in ("EmployeePatchIn", "EmployeeCreateIn", "EmployeeOut"):
    if name not in comps:
        print(f"\n=== {name} === MISSING")
        continue
    props = comps[name].get("properties", {})
    print(f"\n=== {name} property names ===")
    for k in sorted(props):
        print(f"  {k}")

for name in ("AssignmentCreateIn", "AssignmentPatchIn", "AssignmentOut"):
    if name not in comps:
        print(f"\n=== {name} === MISSING")
        continue
    print(f"\n=== {name} ===")
    print(json.dumps(comps[name], indent=2)[:2000])

print("\n=== paths mentioning 'shift' ===")
for p in sorted(s.get("paths", {})):
    if "shift" in p.lower():
        print(f"  {p}")