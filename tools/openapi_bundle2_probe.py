import json
from app.main import app

s = app.openapi()
comps = s.get("components", {}).get("schemas", {})
paths = s.get("paths", {})

print("=== Employee PATCH body (EmployeePatchIn?) ===")
for name in comps:
    if "Employee" in name and ("Patch" in name or "Update" in name):
        print(f"-- {name} --")
        print(json.dumps(comps[name], indent=2)[:2500])

print("\n=== EmployeeCreateIn (for site_id / default_shift_id on create) ===")
for name in comps:
    if "EmployeeCreate" in name or "EmployeeIn" in name:
        print(f"-- {name} --")
        print(json.dumps(comps[name], indent=2)[:2500])

print("\n=== EmployeeWorkPattern endpoints ===")
for p in sorted(paths):
    if "work-pattern" in p and "employee" in p:
        print("PATH:", p)
        for meth, op in paths[p].items():
            if meth in ("get", "post", "patch", "put", "delete"):
                print("  ", meth.upper())
                rb = op.get("requestBody", {})
                if rb:
                    print("    reqBody:", json.dumps(rb)[:800])

print("\n=== WorkPattern assignment schemas ===")
for name in comps:
    if "WorkPattern" in name:
        print(f"-- {name} --")
        print(json.dumps(comps[name], indent=2)[:1500])

print("\n=== Employee endpoint field name conventions ===")
p = paths.get("/api/v1/employees/{employee_id}", {})
for meth, op in p.items():
    if meth in ("get", "patch"):
        print(meth.upper(), ":", op.get("summary", ""))