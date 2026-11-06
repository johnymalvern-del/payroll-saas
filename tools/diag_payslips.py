"""Diagnose /payslips "Could not load". Read-only."""
import json, sys, urllib.request, urllib.error

API = "http://localhost:8000/api/v1"
H = {"Content-Type": "application/json", "X-Tenant-Slug": "tenant-demo"}


def call(m, p, b=None, tok=None):
    h = dict(H)
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    data = json.dumps(b).encode() if b is not None else None
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(API + p, data=data, headers=h, method=m)
        )
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:500]
    except Exception as e:
        return 0, str(e)


# --- admin ---
s, body = call("POST", "/auth/login", {"identifier": "admin", "password": "devpass_admin"})
print(f"admin LOGIN: {s}")
if s != 200:
    print(body); sys.exit(1)
tok = body["access_token"]

s, me = call("GET", "/auth/me", tok=tok)
print(f"\nadmin /auth/me: {s}")
if isinstance(me, dict):
    print(f"  employee_id: {me.get('employee_id')!r}")
    print(f"  role: {me.get('role')}")

s, ps = call("GET", "/payroll/payslips/me", tok=tok)
print(f"\nadmin /payroll/payslips/me: {s}")
print(f"  body: {json.dumps(ps)[:500] if isinstance(ps, (dict, list)) else ps}")

s, periods = call("GET", "/payroll/pay-periods?limit=20", tok=tok)
print(f"\nadmin /payroll/pay-periods: {s}")
if isinstance(periods, dict):
    for p in periods.get("items", []):
        print(f"  {p.get('period_key')}  status={p.get('status')}  {p.get('start_date')}..{p.get('end_date')}")

s, f = call("GET", "/payroll/formulas/readiness", tok=tok)
print(f"\n/payroll/formulas/readiness: {s}")
print(f"  {json.dumps(f)[:400] if isinstance(f, dict) else f}")

s, st = call("GET", "/payroll/settings", tok=tok)
print(f"\n/payroll/settings: {s}")
if isinstance(st, dict):
    print(f"  demo_values: {st.get('demo_values')}")
    print(f"  formula_acks: {list((st.get('formula_acks') or {}).keys())}")
    print(f"  attendance_earning_map keys: {list((st.get('attendance_earning_map') or {}).keys())}")

# --- employee user ---
print("\n--- employee/devpass_employee ---")
s, body = call("POST", "/auth/login", {"identifier": "employee", "password": "devpass_employee"})
print(f"LOGIN: {s}")
if s == 200:
    etok = body["access_token"]
    s, eme = call("GET", "/auth/me", tok=etok)
    if isinstance(eme, dict):
        print(f"  employee_id: {eme.get('employee_id')!r}")
    s, eps = call("GET", "/payroll/payslips/me", tok=etok)
    print(f"  /payroll/payslips/me: {s}")
    print(f"  body: {json.dumps(eps)[:500] if isinstance(eps, (dict, list)) else eps}")