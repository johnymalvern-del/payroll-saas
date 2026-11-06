"""Seed Oct 2026 full + Nov 2026 up to today for T001-T010 with variety.

- Worked days -> punches via API (retry on 429)
- Absent/leave/sick -> direct AttendanceDay insert (deterministic pattern)
- Idempotent: skips existing (employee, date)
- Also fills the 3 failed Nov punches from the previous run
"""
import os, json, sys, time, uuid, urllib.request, urllib.error, calendar
from datetime import date, datetime, timezone, timedelta

os.environ.setdefault(
    "DATABASE_URL_CONTROL",
    "postgresql+psycopg://payroll_app:payroll_app_dev_password@localhost:5432/payroll_control",
)

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.db.tenant.models.attendance import AttendanceDay

TENANT_DB = "tenant_tenant_demo"
DB_URL = (
    f"postgresql+psycopg://payroll_app:payroll_app_dev_password"
    f"@localhost:5432/{TENANT_DB}"
)
API = "http://localhost:8000/api/v1"
H = {"Content-Type": "application/json", "X-Tenant-Slug": "tenant-demo"}


def api(m, p, b=None, tok=None, extra=None):
    h = dict(H)
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    if extra:
        h.update(extra)
    data = json.dumps(b).encode() if b is not None else None
    for attempt in range(4):
        try:
            r = urllib.request.urlopen(
                urllib.request.Request(API + p, data=data, headers=h, method=m)
            )
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:
                time.sleep(2 + attempt * 2)
                continue
            return e.code, e.read().decode()[:300]
        except Exception as e:
            return 0, str(e)


# login
s, body = api("POST", "/auth/login", {"identifier": "admin", "password": "devpass_admin"})
if s != 200:
    print(f"Login failed: {s} {body}"); sys.exit(1)
tok = body["access_token"]

# employees
s, eb = api("GET", "/employees?limit=500&status=active", tok=tok)
if s != 200:
    print(f"Employees fetch failed: {s} {eb}"); sys.exit(1)
emps = [e for e in eb["items"] if e["employee_code"].startswith("T0")]
print(f"Employees: {len(emps)}")

# device keys
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

# DB
engine = create_engine(DB_URL, future=True)
sess = Session(engine)

today = date.today()


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


NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def punch(emp_id, sid, dt_iso):
    cid = uuid.uuid5(NS, f"month-{emp_id}-{dt_iso}")
    body = {
        "client_punch_id": str(cid),
        "employee_id": emp_id,
        "device_time": dt_iso,
        "method": "fingerprint",
    }
    return api(
        "POST", "/punches", body, tok=tok, extra={"X-Device-Key": keys[sid]}
    )[0]


def special_status(emp_idx, d):
    """Each employee gets ~2 absent + 1 leave + 1 sick per month, spread."""
    key = (emp_idx * 11 + d.day * 3) % 17
    if key in (0, 7):
        return "absent"
    if key == 4:
        return "leave"
    if key == 9:
        return "sick"
    return None


worked = non_worked = skipped = errors = 0
for i, e in enumerate(emps):
    sid = e.get("site_id")
    if not sid or sid not in keys:
        print(f"- {e['employee_code']}: no device"); continue
    shift_id = e.get("default_shift_id")

    for target in [
        date(today.year, 10, 1),
        date(today.year, 11, 1),
    ]:
        if target > today:
            continue
        last = date(
            target.year, target.month,
            calendar.monthrange(target.year, target.month)[1],
        )
        end = min(today, last)
        cur = target
        while cur <= end:
            if cur.weekday() >= 5:
                cur += timedelta(days=1); continue
            if has_day(e["id"], cur):
                skipped += 1; cur += timedelta(days=1); continue
            st = special_status(i, cur)
            if st:
                insert_non_worked(e["id"], cur, st, shift_id)
                non_worked += 1
            else:
                ds = cur.isoformat()
                s1 = punch(e["id"], sid, f"{ds}T08:00:00+02:00")
                s2 = punch(e["id"], sid, f"{ds}T17:00:00+02:00")
                if s1 in (200, 201) and s2 in (200, 201):
                    worked += 1
                else:
                    errors += 1
                    print(f"! {e['employee_code']} {cur} IN={s1} OUT={s2}")
                time.sleep(0.15)
            cur += timedelta(days=1)
    print(f"+ {e['employee_code']} {e['first_name']}")

sess.close()
print(
    f"\nWorked: {worked} | Non-worked: {non_worked} | Skipped: {skipped} | Errors: {errors}"
)
print("Sheet month picker -> Oct 2026 or Nov 2026 to see the variety.")