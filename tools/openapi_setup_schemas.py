import json
from app.main import app

s = app.openapi()
comps = s.get("components", {}).get("schemas", {})
paths = s.get("paths", {})

entities = {
    "Site": "/api/v1/sites",
    "Branch": "/api/v1/branches",
    "Department": "/api/v1/departments",
    "Shift": "/api/v1/shifts",
    "WorkPattern": "/api/v1/work-patterns",
    "PublicHoliday": "/api/v1/public-holidays",
}

for entity, base in entities.items():
    print(f"\n=== {entity} — paths ===")
    for p in sorted(paths):
        if base in p or (entity == "WorkPattern" and "/work-patterns" in p):
            methods = [m.upper() for m in paths[p] if m in ("get","post","patch","put","delete")]
            print(f"  {p}: {methods}")
    for suffix in ("CreateIn", "PatchIn", "ListOut"):
        name = entity + suffix
        if name in comps:
            props = list(comps[name].get("properties", {}).keys())
            req = comps[name].get("required", [])
            print(f"  {name}: props={props}")
            if req:
                print(f"    required={req}")

print("\n=== RateRule schemas ===")
for n in sorted(comps):
    if "RateRule" in n:
        props = list(comps[n].get("properties", {}).keys())
        req = comps[n].get("required", [])
        print(f"  {n}: props={props}")
        if req:
            print(f"    required={req}")

print("\n=== PublicHoliday POST present? ===")
ph = paths.get("/api/v1/public-holidays", {})
print("  methods:", [m.upper() for m in ph if m in ("get","post")])