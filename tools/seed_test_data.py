"""Seed the running tenant-demo with a test dataset via the live API.

Creates: 3 branches, 4 departments, 4 sites, 4 shifts, 2 work patterns,
10 employees. Idempotent — anything that already exists by name/code is
skipped. Prints + for created, = for existing, ! for failure.

Login: admin / devpass_admin. Base: http://localhost:8000.
Tenant: tenant-demo (must match frontend/.env.local VITE_TENANT_SLUG).
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8000/api/v1"
TENANT = "tenant-demo"
H = {"Content-Type": "application/json", "X-Tenant-Slug": TENANT}


def call(method, path, body=None, token=None):
    h = dict(H)
    if token:
        h["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(BASE + path, data=data, headers=h, method=method)
        )
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:
        return 0, str(e)


def find_id(list_path, key, value, token):
    s, body = call("GET", list_path + "?limit=500", token=token)
    if s != 200 or not isinstance(body, dict):
        return None
    for item in body.get("items", []):
        if item.get(key) == value:
            return item["id"]
    return None


# ---- login ----
s, body = call("POST", "/auth/login", {"identifier": "admin", "password": "devpass_admin"})
if s != 200:
    print(f"Login failed: {s} {body}")
    print("Is backend up on localhost:8000? Is admin/devpass_admin correct?")
    sys.exit(1)
token = body["access_token"]
print("Logged in as admin\n")

# ---- branches ----
BRANCHES = [
    {"name": "Johannesburg HQ", "code": "JHB", "address": "1 Sandton Drive, Sandton"},
    {"name": "Cape Town Office", "code": "CPT", "address": "1 Foreshore Place, Cape Town"},
    {"name": "Durban Branch", "code": "DBN", "address": "1 Florida Road, Durban"},
]
branch_ids = {}
for b in BRANCHES:
    s, body = call("POST", "/branches", b, token)
    if s in (200, 201):
        branch_ids[b["code"]] = body["id"]
        print(f"+ branch {b['code']:6} {b['name']}")
    else:
        eid = find_id("/branches", "code", b["code"], token)
        if eid:
            branch_ids[b["code"]] = eid
            print(f"= branch {b['code']:6} exists")
        else:
            print(f"! branch {b['code']} failed: {s} {body}")

# ---- departments ----
DEPARTMENTS = [
    {"name": "Operations", "code": "OPS"},
    {"name": "Sales", "code": "SALES"},
    {"name": "Finance", "code": "FIN"},
    {"name": "Human Resources", "code": "HR"},
]
dept_ids = {}
for d in DEPARTMENTS:
    s, body = call("POST", "/departments", d, token)
    if s in (200, 201):
        dept_ids[d["code"]] = body["id"]
        print(f"+ dept   {d['code']:6} {d['name']}")
    else:
        eid = find_id("/departments", "code", d["code"], token)
        if eid:
            dept_ids[d["code"]] = eid
            print(f"= dept   {d['code']:6} exists")
        else:
            print(f"! dept {d['code']} failed: {s} {body}")

# ---- sites ----
SITES = [
    {"branch_id": branch_ids.get("JHB"), "name": "Sandton HQ", "code": "S-SANDTON",
     "timezone": "Africa/Johannesburg", "site_type": "head_office", "address": "1 Sandton Drive"},
    {"branch_id": branch_ids.get("JHB"), "name": "Midrand Warehouse", "code": "S-MIDRAND",
     "timezone": "Africa/Johannesburg", "site_type": "warehouse"},
    {"branch_id": branch_ids.get("CPT"), "name": "Foreshore", "code": "S-FORESHORE",
     "timezone": "Africa/Johannesburg", "site_type": "office"},
    {"branch_id": branch_ids.get("DBN"), "name": "Florida Road", "code": "S-FLORIDA",
     "timezone": "Africa/Johannesburg", "site_type": "office"},
]
site_ids = {}
for site in SITES:
    if not site.get("branch_id"):
        print(f"! site {site['code']} skipped (no branch)")
        continue
    s, body = call("POST", "/sites", site, token)
    if s in (200, 201):
        site_ids[site["code"]] = body["id"]
        print(f"+ site   {site['code']:12} {site['name']}")
    else:
        eid = find_id("/sites", "code", site["code"], token)
        if eid:
            site_ids[site["code"]] = eid
            print(f"= site   {site['code']:12} exists")
        else:
            print(f"! site {site['code']} failed: {s} {body}")

# ---- shifts ----
SHIFTS = [
    {"name": "Day 08:00-17:00", "start_time": "08:00", "length_minutes": 480,
     "max_shift_minutes": 600, "unpaid_break_minutes": 60},
    {"name": "Morning 06:00-14:00", "start_time": "06:00", "length_minutes": 480,
     "max_shift_minutes": 600},
    {"name": "Afternoon 14:00-22:00", "start_time": "14:00", "length_minutes": 480,
     "max_shift_minutes": 600},
    {"name": "Night 22:00-06:00", "start_time": "22:00", "length_minutes": 480,
     "max_shift_minutes": 600},
]
shift_ids = {}
for sh in SHIFTS:
    s, body = call("POST", "/shifts", sh, token)
    if s in (200, 201):
        shift_ids[sh["name"]] = body["id"]
        print(f"+ shift  {sh['name']}")
    else:
        eid = find_id("/shifts", "name", sh["name"], token)
        if eid:
            shift_ids[sh["name"]] = eid
            print(f"= shift  {sh['name']} exists")
        else:
            print(f"! shift {sh['name']} failed: {s} {body}")

# ---- work patterns ----
def days_for(expected_flags):
    return [{"day_index": i, "is_expected": bool(f)}
            for i, f in enumerate(expected_flags)]

PATTERNS = [
    {"name": "Standard Mon-Fri", "cycle_length_days": 7, "anchor_date": "2026-01-05",
     "days": days_for([1, 1, 1, 1, 1, 0, 0])},
    {"name": "Mon-Sat (retail)", "cycle_length_days": 7, "anchor_date": "2026-01-05",
     "days": days_for([1, 1, 1, 1, 1, 1, 0])},
]
pattern_ids = {}
for pat in PATTERNS:
    s, body = call("POST", "/work-patterns", pat, token)
    if s in (200, 201):
        pattern_ids[pat["name"]] = body["id"]
        print(f"+ patt   {pat['name']}")
    else:
        eid = find_id("/work-patterns", "name", pat["name"], token)
        if eid:
            pattern_ids[pat["name"]] = eid
            print(f"= patt   {pat['name']} exists")
        else:
            print(f"! pattern {pat['name']} failed: {s} {body}")

# ---- employees ----
DAY = shift_ids.get("Day 08:00-17:00")
MORNING = shift_ids.get("Morning 06:00-14:00")
AFTERNOON = shift_ids.get("Afternoon 14:00-22:00")
NIGHT = shift_ids.get("Night 22:00-06:00")
STD = pattern_ids.get("Standard Mon-Fri")
RETAIL = pattern_ids.get("Mon-Sat (retail)")

def emp(code, first, last, hire, site, dept, shift, patt, title):
    return {
        "employee_code": code, "first_name": first, "last_name": last,
        "hire_date": hire, "status": "active",
        "site_id": site, "department_id": dept,
        "default_shift_id": shift, "work_pattern_id": patt,
        "job_title": title,
        "employee_type": "hourly", "pay_basis": "hourly",
        "pay_frequency": "monthly",
    }

EMPLOYEES = [
    emp("T001", "Thabo",    "Mokoena",   "2024-03-01", site_ids.get("S-SANDTON"),   dept_ids.get("OPS"),   DAY,       STD,    "Operations Manager"),
    emp("T002", "Naledi",   "Khumalo",   "2024-06-15", site_ids.get("S-SANDTON"),   dept_ids.get("FIN"),   DAY,       STD,    "Financial Accountant"),
    emp("T003", "Sipho",    "Dlamini",   "2023-09-01", site_ids.get("S-MIDRAND"),   dept_ids.get("OPS"),   MORNING,   RETAIL, "Warehouse Lead"),
    emp("T004", "Lerato",   "Mahlangu",  "2024-01-15", site_ids.get("S-FORESHORE"), dept_ids.get("SALES"), DAY,       STD,    "Sales Representative"),
    emp("T005", "Andile",   "Nkosi",     "2024-11-01", site_ids.get("S-FLORIDA"),   dept_ids.get("OPS"),   AFTERNOON, RETAIL, "Site Supervisor"),
    emp("T006", "Precious", "Mabaso",    "2023-12-01", site_ids.get("S-SANDTON"),   dept_ids.get("HR"),    DAY,       STD,    "HR Officer"),
    emp("T007", "Kagiso",   "Radebe",    "2024-08-01", site_ids.get("S-MIDRAND"),   dept_ids.get("OPS"),   NIGHT,     RETAIL, "Night Shift Operator"),
    emp("T008", "Zanele",   "Mthethwa",  "2024-04-15", site_ids.get("S-FORESHORE"), dept_ids.get("SALES"), DAY,       STD,    "Account Executive"),
    emp("T009", "Bongani",  "Zulu",      "2024-02-01", site_ids.get("S-FLORIDA"),   dept_ids.get("SALES"), MORNING,   RETAIL, "Retail Assistant"),
    emp("T010", "Nomsa",    "Botha",     "2024-07-01", site_ids.get("S-SANDTON"),   dept_ids.get("FIN"),   DAY,       STD,    "Payroll Clerk"),
]
for e in EMPLOYEES:
    s, body = call("POST", "/employees", e, token)
    if s in (200, 201):
        print(f"+ emp    {e['employee_code']} {e['first_name']} {e['last_name']}")
    elif s in (400, 409, 422):
        eid = find_id("/employees", "employee_code", e["employee_code"], token)
        if eid:
            print(f"= emp    {e['employee_code']} exists")
        else:
            print(f"! emp {e['employee_code']} failed: {s} {str(body)[:180]}")
    else:
        print(f"! emp {e['employee_code']} failed: {s} {str(body)[:180]}")

print("\nDone. Open /setup and /employees in the browser.")
print("If P1 theme is on, the shell sidebar groups should now show data-rich pages.")