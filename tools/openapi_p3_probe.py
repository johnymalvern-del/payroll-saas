import json, urllib.request, urllib.error
from app.main import app

s = app.openapi()
comps = s.get("components", {}).get("schemas", {})

# 1. DayDetailOut schema
print("=== DayDetailOut ===")
if "DayDetailOut" in comps:
    print(json.dumps(comps["DayDetailOut"], indent=2)[:3000])

# 2. AttendanceSegmentOut
for n in comps:
    if "Segment" in n:
        print(f"\n=== {n} ===")
        print(json.dumps(comps[n], indent=2)[:2000])

# 3. adjustment list filters
print("\n=== GET /attendance/adjustments params ===")
p = s["paths"].get("/api/v1/attendance/adjustments", {}).get("get", {})
for param in p.get("parameters", []):
    print(f"  {param['in']:8} {param['name']:20} required={param.get('required')}")

# 4. punch photo access
print("\n=== photo-related paths ===")
for pth in sorted(s["paths"]):
    if "photo" in pth or "punch" in pth:
        print(f"  {pth}: {[m.upper() for m in s['paths'][pth] if m in ('get','post')]}")

# 5. attendance_day fields (from AttendanceDayOut? DayListOut item)
for n in comps:
    if n in ("DayDetailOut", "AttendanceDayOut"):
        print(f"\n=== {n} has these keys ===")
        print(" ", list(comps[n].get("properties", {}).keys()))