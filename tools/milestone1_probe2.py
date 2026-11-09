"""Milestone 1 — probe #2: FORMULA_REGISTRY, rate lookup, EMP0001 attendance."""
import sys
import inspect
from pathlib import Path
from datetime import date
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

URL = (
    "postgresql+psycopg://payroll_test:payroll_test_dev_password"
    "@localhost:5432/tenant_tenant_demo"
)

from app.db.tenant.models.people import Employee, EmployeePayHistory
from app.db.tenant.models.attendance import AttendanceDay, AttendanceSegment
from app.db.tenant.models.pay import PayPeriod
from app.services import payroll_runner as pr

print("=== FORMULA_REGISTRY ===")
reg = getattr(pr, "FORMULA_REGISTRY", None)
if reg is None:
    print("  NOT FOUND on payroll_runner")
else:
    print(f"  type: {type(reg)}")
    if isinstance(reg, dict):
        for k, v in reg.items():
            print(f"  {k}")
    elif isinstance(reg, (list, tuple)):
        for v in reg:
            print(f"  {v}")
    else:
        print(f"  value: {reg}")

print("\n=== _load_settings SOURCE ===")
print(inspect.getsource(pr._load_settings))

print("\n=== _rate_in_force_for SOURCE ===")
print(inspect.getsource(pr._rate_in_force_for))

print("\n=== build_pipeline_config SOURCE ===")
print(inspect.getsource(pr.build_pipeline_config))

eng = create_engine(URL)
s = Session(eng)
try:
    emp = s.scalar(select(Employee).where(Employee.employee_code == "EMP0001"))
    if emp is None:
        print("\nEMP0001 NOT FOUND")
    else:
        print(f"\n=== EMP0001 details ===")
        print(f"  id={emp.id}")
        print(f"  employee_code={emp.employee_code}")
        print(f"  first_name={emp.first_name}, last_name={emp.last_name}")
        print(f"  pay_basis={emp.pay_basis}, pay_frequency={emp.pay_frequency}")
        print(f"  base_rate={emp.base_rate}")
        print(f"  hire_date={emp.hire_date}")
        print(f"  status={emp.status}")
        print(f"  site_id={emp.site_id}, default_shift_id={emp.default_shift_id}")
        print(f"  work_pattern_id={emp.work_pattern_id}")

        hist = s.scalars(
            select(EmployeePayHistory).where(
                EmployeePayHistory.employee_id == emp.id
            )
        ).all()
        print(f"  pay_history rows: {len(hist)}")
        for h in hist:
            print(
                f"    base_rate={h.base_rate} status={h.status} "
                f"effective_from={h.effective_from} effective_to={h.effective_to}"
            )

    period = s.scalar(select(PayPeriod).where(PayPeriod.period_key == "2026_11"))
    if period is None:
        print("\nNOV 2026 PERIOD NOT FOUND")
    else:
        print(f"\n=== EMP0001 ATTENDANCE in Nov 2026 ===")
        days = s.scalars(
            select(AttendanceDay).where(
                AttendanceDay.employee_id == emp.id,
                AttendanceDay.work_date >= period.start_date,
                AttendanceDay.work_date <= period.end_date,
            ).order_by(AttendanceDay.work_date)
        ).all()
        print(f"  days: {len(days)}")
        all_keys = set()
        total_normal_min = 0
        total_ot_min = 0
        for d in days:
            segs = s.scalars(
                select(AttendanceSegment).where(
                    AttendanceSegment.attendance_day_id == d.id
                )
            ).all()
            seg_summary = ", ".join(
                f"{sg.kind}/{sg.day_type}/t{sg.tier}/"
                f"{sg.minutes}min/{sg.rate_method}={sg.rate_value}"
                for sg in segs
            )
            print(
                f"  {d.work_date} status={d.status} "
                f"worked={d.worked_minutes} locked={d.locked} "
                f"shift={d.shift_id} segments=[{seg_summary}]"
            )
            for sg in segs:
                all_keys.add(pr._group_key_for_segment(sg))
                if sg.kind == "normal":
                    total_normal_min += sg.minutes
                elif sg.kind == "overtime":
                    total_ot_min += sg.minutes

        print(f"\n  _group_key_for_segment keys emitted by EMP0001 Nov 2026:")
        for k in sorted(all_keys):
            print(f"    {k}")
        print(f"\n  Total normal minutes: {total_normal_min}")
        print(f"  Total overtime minutes: {total_ot_min}")
        if emp.base_rate is not None:
            hourly_rate = float(emp.base_rate)
            exp_normal = (total_normal_min / 60.0) * hourly_rate
            print(f"  Expected normal_pay (hourly × rate): "
                  f"{total_normal_min}/60 × {hourly_rate} = {exp_normal:.2f}")
            exp_ot_1_5 = (total_ot_min / 60.0) * hourly_rate * 1.5
            print(f"  Expected overtime (×1.5 if that tier's method=multiplier): "
                  f"{exp_ot_1_5:.2f}")

    # All distinct segment group keys across the whole tenant (for map fill)
    print(f"\n=== ALL distinct _group_key_for_segment across tenant ===")
    segs_all = s.scalars(select(AttendanceSegment)).all()
    all_tenant_keys = set()
    for sg in segs_all:
        all_tenant_keys.add(pr._group_key_for_segment(sg))
    for k in sorted(all_tenant_keys):
        print(f"    {k}")

    # Which EMP0001 employee_work_pattern is set, if any
    from app.db.tenant.models.attendance import EmployeeWorkPattern
    ewps = s.scalars(
        select(EmployeeWorkPattern).where(
            EmployeeWorkPattern.employee_id == emp.id
        )
    ).all()
    print(f"\n=== EMP0001 employee_work_pattern rows: {len(ewps)} ===")
    for e in ewps:
        print(
            f"  pattern={e.work_pattern_id} "
            f"from={e.effective_from} to={e.effective_to}"
        )

finally:
    s.close()
    eng.dispose()