"""Milestone 1 — probe #5. Ground truth: did punches create attendance days?"""
import sys
from pathlib import Path
from datetime import date
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

TENANT_URL = (
    "postgresql+psycopg://payroll_test:payroll_test_dev_password"
    "@localhost:5432/tenant_tenant_demo"
)

from app.db.tenant.models.people import Employee
from app.db.tenant.models.attendance import (
    AttendanceDay, AttendanceSegment, Punch,
)

eng = create_engine(TENANT_URL)
s = Session(eng)
try:
    t001 = s.scalar(select(Employee).where(Employee.employee_code == "T001"))
    if t001 is None:
        sys.exit("T001 missing")
    print(f"T001 id = {t001.id}")
    print(f"T001 shift = {t001.default_shift_id}")
    print(f"T001 work_pattern = {t001.work_pattern_id}")
    print(f"T001 site = {t001.site_id}")

    print("\n=== Punch rows for T001 (from Nov 1) ===")
    punches = s.execute(
        text(
            "SELECT id, effective_time, method, device_time, "
            "server_received_at, offset_ms "
            "FROM punch WHERE employee_id = :eid "
            "AND effective_time >= '2026-11-01' "
            "ORDER BY effective_time"
        ),
        {"eid": str(t001.id)},
    ).all()
    print(f"  count: {len(punches)}")
    for p in punches:
        print(f"    {p}")

    print("\n=== All Punch rows in DB (last 15) ===")
    all_p = s.execute(
        text(
            "SELECT employee_id, effective_time, method "
            "FROM punch ORDER BY server_received_at DESC LIMIT 15"
        )
    ).all()
    print(f"  count: {len(all_p)}")
    for p in all_p:
        print(f"    emp={p[0]} eff={p[1]} method={p[2]}")

    print("\n=== AttendanceDay rows for T001 (Nov 2026) ===")
    days = s.execute(
        text(
            "SELECT id, work_date, status, first_in, last_out, "
            "worked_minutes, shift_id, locked "
            "FROM attendance_day WHERE employee_id = :eid "
            "AND work_date >= '2026-11-01' AND work_date <= '2026-11-30' "
            "ORDER BY work_date"
        ),
        {"eid": str(t001.id)},
    ).all()
    print(f"  count: {len(days)}")
    for d in days:
        print(f"    {d}")

    print("\n=== TOTAL attendance_days count ===")
    total = s.execute(text("SELECT COUNT(*) FROM attendance_day")).scalar()
    print(f"  total in DB: {total}")

    print("\n=== All attendance_days in Nov 2026 (any employee) ===")
    nov = s.execute(
        text(
            "SELECT employee_id, work_date, status, worked_minutes "
            "FROM attendance_day WHERE work_date >= '2026-11-01' "
            "AND work_date <= '2026-11-30' ORDER BY work_date LIMIT 20"
        )
    ).all()
    print(f"  count: {len(nov)}")
    for n in nov:
        print(f"    {n}")

    print("\n=== AttendanceSegment rows for T001 ===")
    segs = s.execute(
        text(
            "SELECT id, attendance_day_id, kind, day_type, tier, "
            "minutes, rate_method, rate_value "
            "FROM attendance_segment WHERE attendance_day_id IN ("
            "  SELECT id FROM attendance_day WHERE employee_id = :eid "
            "  AND work_date >= '2026-11-01'"
            ") ORDER BY attendance_day_id"
        ),
        {"eid": str(t001.id)},
    ).all()
    print(f"  count: {len(segs)}")
    for sg in segs:
        print(f"    {sg}")

    print("\n=== Check for locked days on T001 ===")
    locked = s.execute(
        text(
            "SELECT work_date, status, locked FROM attendance_day "
            "WHERE employee_id = :eid AND locked = TRUE"
        ),
        {"eid": str(t001.id)},
    ).all()
    print(f"  locked days: {len(locked)}")
    for l in locked:
        print(f"    {l}")
finally:
    s.close()
    eng.dispose()