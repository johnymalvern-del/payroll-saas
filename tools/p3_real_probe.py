"""Fetch a real DayDetailOut response + the frontend normaliser + backend _to_out."""
import json, sys, urllib.request, urllib.error
from datetime import date, timedelta

BASE = "http://localhost:8000/api/v1"
H = {"Content-Type": "application/json", "X-Tenant-Slug": "tenant-demo"}


def call(m, p, b=None, tok=None):
    h = dict(H)
    if tok: h["Authorization"] = f"Bearer {tok}"
    data = json.dumps(b).encode() if b else None
    try:
        r = urllib.request.urlopen(urllib.request.Request(BASE + p, data=data, headers=h, method=m))
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:500]
    except Exception as e:
        return 0, str(e)


s, body = call("POST", "/auth/login", {"identifier": "admin", "password": "devpass_admin"})
if s != 200:
    print(f"Login failed: {s} {body}"); sys.exit(1)
token = body["access_token"]

# find a T0xx employee
s, eb = call("GET", "/employees?limit=500&status=active", tok=token)
emps = [e for e in eb["items"] if e["employee_code"].startswith("T0") and e.get("site_id")]
if not emps:
    print("No T0xx with site"); sys.exit(1)
emp = emps[0]

# yesterday
yd = (date.today() - timedelta(days=1)).isoformat()
print(f"=== GET /attendance/day/{emp['employee_code']} / {yd} ===")
s, day = call("GET", f"/attendance/day/{emp['id']}/{yd}", tok=token)
print(f"status: {s}")
if s == 200:
    print(json.dumps(day, indent=2, default=str)[:3500])
else:
    print(day)

# try exceptions filtered by employee + date
print(f"\n=== GET /attendance/exceptions?employee_id=&from=&to= ===")
s, exc = call("GET", f"/attendance/exceptions?employee_id={emp['id']}&from_date={yd}&to_date={yd}", tok=token)
print(f"status: {s}")
if s == 200:
    print(json.dumps(exc, indent=2, default=str)[:1200])
else:
    print(exc[:300])