"""Milestone 1 — probe #6.

Three tests:
  1. Is country_calendar populated on tenant-demo? (recompute precondition)
  2. Send one punch with device_now_at_send = device_time (test punch offset fix)
  3. Call recompute_day directly (in-process) — catch the real exception
"""
import sys
import json
import time
import uuid
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

TENANT_URL = (
    "postgresql+psycopg://payroll_test:payroll_test_dev_password"
    "@localhost:5432/tenant_tenant_demo"
)
API = "http://localhost:8000/api/v1"
SLUG = "tenant-demo"

from app.db.tenant.models.people import Employee
from app.db.tenant.models.attendance import (
    AttendanceDay, AttendanceSegment, Punch, CountryCalendar,
)
from app.api.v1.attendance_engine import recompute_day, _load_holiday_set


def api(m, p, b=None, tok=None, extra=None):
    h = {"Content-Type": "application/json", "X-Tenant-Slug": SLUG}
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
        return e.code, e.read().decode()[:400]
    except Exception as e:
        return 0, str(e)


eng = create_engine(TENANT_URL)
s = Session(eng)
try:
    t001 = s.scalar(select(Employee).where(Employee.employee_code == "T001"))
    print(f"T001 id={t001.id}")

    # ============================================================
    print("\n=== TEST 1: country_calendar on tenant-demo ===")
    cnt = s.scalar(select(func.count()).select_from(CountryCalendar))
    print(f"  country_calendar total rows: {cnt}")
    if cnt:
        rng = s.execute(text(
            "SELECT country_code, MIN(holiday_date), MAX(holiday_date), "
            "COUNT(*) FROM country_calendar GROUP BY country_code"
        )).all()
        for r in rng:
            print(f"    country={r[0]} from={r[1]} to={r[2]} count={r[3]}")

    print("\n=== TEST 1b: _load_holiday_set direct call for 2026 ===")
    try:
        hs = _load_holiday_set(s, "ZA", date(2026, 1, 1), date(2026, 12, 31))
        print(f"  OK: {len(hs)} holidays returned")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")

    # ============================================================
    print("\n=== TEST 2: recompute_day IN-PROCESS on Nov 4 (no new punches) ===")
    try:
        d = recompute_day(s, t001.id, date(2026, 11, 4))
        if d is None:
            print("  recompute returned None")
        else:
            print(f"  recompute returned: id={d.id} "
                  f"work_date={d.work_date} status={d.status} "
                  f"first_in={d.first_in} last_out={d.last_out} "
                  f"worked_minutes={d.worked_minutes}")
        s.commit()
    except Exception as e:
        print(f"  RAISED: {type(e).__name__}: {e}")
        s.rollback()

    # ============================================================
    print("\n=== TEST 3: send ONE punch with device_now_at_send = device_time ===")
    s_api, body = api("POST", "/auth/login",
                      {"identifier": "admin", "password": "devpass_admin"})
    if s_api != 200:
        print(f"  login failed: {s_api} {body}")
        sys.exit(1)
    token = body["access_token"]

    # Get device key
    s_api, devs = api("GET", "/devices?limit=100", tok=token)
    dev_key = None
    for d in (devs.get("items", []) if isinstance(devs, dict) else []):
        if d.get("site_id") == str(t001.site_id):
            s_api, rot = api("POST", f"/devices/{d['id']}/rotate-key", tok=token)
            if s_api == 200:
                dev_key = rot["api_key"]
            break
    if dev_key is None:
        print(f"  no device found")
        sys.exit(1)

    # Punch Nov 12 08:00, with device_now_at_send = device_time
    test_dt = "2026-11-12T08:00:00+02:00"
    test_dt_out = "2026-11-12T17:00:00+02:00"
    for which, dt in (("in", test_dt), ("out", test_dt_out)):
        cid = uuid.uuid5(uuid.NAMESPACE_DNS, f"probe6-{t001.id}-{dt}-{which}")
        s_api, resp = api(
            "POST", "/punches",
            {
                "client_punch_id": str(cid),
                "employee_id": str(t001.id),
                "device_time": dt,
                "device_now_at_send": dt,   # <-- key test
                "method": "fingerprint",
            },
            tok=token, extra={"X-Device-Key": dev_key},
        )
        print(f"  punch {which} {dt}: HTTP {s_api}")
        if s_api >= 400:
            print(f"    body: {resp}")
        time.sleep(0.3)

    # Inspect what landed
    s.expire_all()
    punches = s.execute(
        text(
            "SELECT effective_time, device_time, device_now_at_send, offset_ms "
            "FROM punch WHERE employee_id = :eid "
            "AND device_time::date = '2026-11-12' ORDER BY effective_time"
        ),
        {"eid": str(t001.id)},
    ).all()
    print(f"\n  punches stored for Nov 12: {len(punches)}")
    for p in punches:
        print(f"    effective={p[0]} device={p[1]} now={p[2]} offset_ms={p[3]}")

    # Did recompute create an attendance day?
    day = s.scalar(
        select(AttendanceDay).where(
            AttendanceDay.employee_id == t001.id,
            AttendanceDay.work_date == date(2026, 11, 12),
        )
    )
    if day is None:
        print(f"\n  NO attendance_day for Nov 12 (recompute didn't fire or failed)")
    else:
        print(f"\n  attendance_day Nov 12: id={day.id} status={day.status} "
              f"worked={day.worked_minutes} first_in={day.first_in} "
              f"last_out={day.last_out}")
        segs = s.scalars(
            select(AttendanceSegment).where(
                AttendanceSegment.attendance_day_id == day.id
            )
        ).all()
        print(f"  segments: {len(segs)}")
        for sg in segs:
            print(f"    {sg.kind}/{sg.day_type}/tier{sg.tier}/"
                  f"{sg.minutes}min ×{sg.rate_value} ({sg.rate_method})")

    # ============================================================
    print("\n=== TEST 4: explicit recompute on Nov 12 ===")
    try:
        d = recompute_day(s, t001.id, date(2026, 11, 12))
        s.commit()
        if d is None:
            print("  recompute returned None")
        else:
            print(f"  OK: id={d.id} status={d.status} "
                  f"worked={d.worked_minutes}")
            segs = s.scalars(
                select(AttendanceSegment).where(
                    AttendanceSegment.attendance_day_id == d.id
                )
            ).all()
            print(f"  segments after explicit recompute: {len(segs)}")
            for sg in segs:
                print(f"    {sg.kind}/{sg.day_type}/tier{sg.tier}/"
                      f"{sg.minutes}min ×{sg.rate_value}")
    except Exception as e:
        print(f"  RAISED: {type(e).__name__}: {e}")
        s.rollback()

finally:
    s.close()
    eng.dispose()