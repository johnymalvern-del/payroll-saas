"""Seed a full month of attendance variety for T001-T010.

- Worked days -> 2 punches each via API (in 08:00, out 17:00).
- Non-worked days -> direct AttendanceDay insert (absent/leave/sick).
- Idempotent: skips (employee, date) that already has a row.
- Retries on 429.
"""
import os
os.environ.setdefault(
    "DATABASE_URL_CONTROL",
    "postgresql+psycopg://payroll_app:payroll_app_dev_password@localhost:5432/payroll_control",
)

import calendar, json, sys, time, uuid, urllib.request, urllib.error
from datetime import date, datetime, timezone, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.tenant.models.attendance import AttendanceDay

TENANT_DB = "tenant_tenant_demo"
DB_URL = f"postgresql+psycopg://payroll_app:payroll_app_dev_password@localhost:5432/{TENANT_DB}"
API = "http://localhost:8000/api/v1"
H = {"Content-Type": "application/json", "X-Tenant-Slug": "tenant-demo"}


def api(m, p, b=None, tok=None, extra=None):
    h = dict(H)
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    if extra:
        h.update(extra)
    data = json.dumps(b).encode() if b is not None else None
    try:
        r = urllib.request.urlopen(
            urllib.request.Request(API + p, data=data, headers=h, method=m)
        )
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:
        return 0, str(e)


# ---------- login ----------
s, body = api("POST", "/auth/login", {"identifier": "admin", "password": "devpass_admin"})
if s != 200:
    print(f"Login failed: {s} {body}"); sys.exit(1)
tok = body["access_token"]

# ---------- employees ----------
s, eb = api("GET", "/employees?limit=500&status=active", tok=tok)
if s != 200:
    print(f"Employees fetch failed: {s} {eb}"); sys.exit(1)
emps = [e for e in eb["items"] if e["employee_code"].startswith("T0")]
print(f"Employees: {len(emps)}")

# ---------- device keys ----------
keys = {}
for sid in {e["site_id"] for e in emps if e.get("site_id")}:
    dev_name = f"Seed device {sid[:8]}"
    s, devs = api("GET", "/devices?limit=100", tok=tok)
    if s == 200:
        for d in devs.get("items", []):
            if d["name"] == dev_name:
                s2, rot = api("POST", f"/devices/{d['id']}/rotate-key", tok=tok)
                if s2 == 200:
                    keys[sid] = rot["api_key"]
                break

# ---------- DB session ----------
engine = create_engine(DB_URL, future=True)
sess = Session(engine)

# ---------- date range ----------
today = date.today()
month_start = date(today.year, today.month, 1)
last_day = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
end = min(today, last_day)  # only days that have actually happened

# ---------- special day per employee ----------
SPECIAL = [
    ("absent", 10),
    ("leave", 11),
    ("sick", 12),
    ("absent", 13),
    ("leave", 14),
    ("sick", 15),
    ("absent", 16),
    ("leave", 17),
    ("sick", 18),
    ("absent", 19),
]

NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def has_day(emp_id, wd):
    return sess.scalar(
        select(AttendanceDay.id).where(
            AttendanceDay.employee_id == emp_id,
            AttendanceDay.work_date == wd,
        )
    ) is not None


def insert_non_worked(emp_id, wd, status, shift_id):
    sess.add(
        AttendanceDay(
            id=uuid.uuid4(),
            employee_id=emp_id,
            work_date=wd,
            status=status,
            first_in=None,
            last_out=None,
            worked_minutes=0,
            normal_minutes=0,
            overtime_minutes=0,
            raw_minutes=0,
            shift_id=shift_id,
            flags=[],
            source_version=1,
            locked=False,
            row_version=1,
            computed_at=datetime.now(timezone.utc),
        )
    )
    sess.commit()


def punch(emp_id, sid, dt_iso, retries=3):
    cid = uuid.uuid5(NS, f"month-{emp_id}-{dt_iso}")
    body = {
        "client_punch_id": str(cid),
        "employee_id": emp_id,
        "device_time": dt_iso,
        "method": "fingerprint",
    }
    for attempt in range(retries):
        s, _ = api("POST", "/punches", body, tok=tok,
                   extra={"X-Device-Key": keys[sid]})
        if s == 429:
            time.sleep(2 + attempt)
            continue
        return s
    return s


# ---------- run ----------
created_worked = created_non = skipped = errors = 0
for i, e in enumerate(emps):
    sid = e.get("site_id")
    if not sid or sid not in keys:
        print(f"- {e['employee_code']} no device"); continue
    shift_id = e.get("default_shift_id")
    special_status, special_dom = SPECIAL[i % len(SPECIAL)]

    cur = month_start
    while cur <= end:
        if cur.weekday() >= 5:  # weekend
            cur += timedelta(days=1)
            continue
        if has_day(e["id"], cur):
            skipped += 1
            cur += timedelta(days=1)
            continue

        is_special = cur.day == special_dom
        if is_special:
            insert_non_worked(e["id"], cur, special_status, shift_id)
            created_non += 1
        else:
            ds = cur.isoformat()
            s1 = punch(e["id"], sid, f"{ds}T08:00:00+02:00")
            s2 = punch(e["id"], sid, f"{ds}T17:00:00+02:00")
            if s1 in (200, 201) and s2 in (200, 201):
                created_worked += 1
            else:
                errors += 1
                print(f"! {e['employee_code']} {cur} IN={s1} OUT={s2}")
        cur += timedelta(days=1)
    print(f"+ {e['employee_code']} {e['first_name']} {e['last_name']}")

sess.close()
print(f"\nWorked days: {created_worked} | non-worked: {created_non} | skipped: {skipped} | errors: {errors}")
print(f"Dates covered: {month_start} to {end}")