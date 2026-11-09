"""Milestone 1 — probe #3.

Answers:
- Does build_pipeline_config succeed today on tenant_tenant_demo? (statutory tables)
- Do the existing 42 attendance_days have segments? (recompute path)
- Do any employees have shifts? (segment construction requires shift)
- What is in the control DB statutory tables?
- Does the punch endpoint call recompute?
"""
import sys
import inspect
from pathlib import Path
from datetime import date
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

TENANT_URL = (
    "postgresql+psycopg://payroll_test:payroll_test_dev_password"
    "@localhost:5432/tenant_tenant_demo"
)
CONTROL_URL = (
    "postgresql+psycopg://payroll_test:payroll_test_dev_password"
    "@localhost:5432/payroll_control"
)

from app.db.tenant.models.people import Employee
from app.db.tenant.models.pay import PayPeriod
from app.db.tenant.models.attendance import AttendanceDay, AttendanceSegment
from app.services import payroll_runner as pr
from app.api.v1 import attendance_engine as ae

eng = create_engine(TENANT_URL)
s = Session(eng)
try:
    emp = s.scalar(select(Employee).where(Employee.employee_code == "EMP0001"))
    period = s.scalar(select(PayPeriod).where(PayPeriod.period_key == "2026_11"))

    print("=== TEST 1: build_pipeline_config on EMP0001 (tax tables) ===")
    if emp is None or period is None:
        print("  EMP0001 or Nov period missing")
    else:
        try:
            cfg = pr.build_pipeline_config(s, emp, period.pay_date)
            print(f"  SUCCESS: PipelineConfig created")
            print(f"  periods_per_year={cfg.periods_per_year}")
            print(f"  sdl_applies={cfg.sdl_applies}")
            print(f"  net_pay_floor={cfg.net_pay_floor}")
            print(f"  employee_age={cfg.employee_age}")
            print(f"  uif_rows={len(cfg.uif_rows) if cfg.uif_rows else 0}")
            print(f"  sdl_rows={len(cfg.sdl_rows) if cfg.sdl_rows else 0}")
            print(f"  retirement_rows={len(cfg.retirement_rows) if cfg.retirement_rows else 0}")
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")

    print("\n=== TEST 2: shift / work_pattern per employee ===")
    for e in s.scalars(select(Employee).order_by(Employee.employee_code)):
        print(f"  {e.employee_code:10} shift={e.default_shift_id} "
              f"pattern={e.work_pattern_id} site={e.site_id} "
              f"base_rate={e.base_rate}")

    print("\n=== TEST 3: 42 attendance_days — segments + shift ===")
    days = s.scalars(select(AttendanceDay)).all()
    print(f"  total attendance_days: {len(days)}")
    by_emp: dict = {}
    for d in days:
        seg_count = s.scalar(
            select(func.count()).select_from(AttendanceSegment)
            .where(AttendanceSegment.attendance_day_id == d.id)
        )
        e = s.get(Employee, d.employee_id)
        code = e.employee_code if e else "?"
        by_emp.setdefault(code, {"days": 0, "with_segs": 0, "with_shift": 0})
        by_emp[code]["days"] += 1
        if seg_count:
            by_emp[code]["with_segs"] += 1
        if d.shift_id is not None:
            by_emp[code]["with_shift"] += 1
    for code, stats in sorted(by_emp.items()):
        print(f"  {code}: days={stats['days']} "
              f"with_segs={stats['with_segs']} with_shift={stats['with_shift']}")

    print("\n=== TEST 4: control DB tables + row counts ===")
    ceng = create_engine(CONTROL_URL)
    cs = Session(ceng)
    try:
        tables = cs.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "ORDER BY tablename"
        )).all()
        print(f"  control tables: {len(tables)}")
        for t in tables:
            cnt = cs.execute(text(f'SELECT COUNT(*) FROM "{t[0]}"')).scalar()
            print(f"    {t[0]}: {cnt}")
    finally:
        cs.close()
        ceng.dispose()

    print("\n=== TEST 5: punch endpoint — recompute calls? ===")
    punches_path = Path(str(Path(__file__).resolve().parent.parent / "backend"
                            / "app" / "api" / "v1" / "punches.py"))
    src = punches_path.read_text(encoding="utf-8")
    hits = []
    for i, ln in enumerate(src.split("\n"), 1):
        low = ln.lower()
        if "recompute" in low or "engine" in low or "attendance_day" in low:
            hits.append(f"  L{i}: {ln.strip()[:140]}")
    print("\n".join(hits) if hits else "  (no recompute / engine / attendance_day references in punches.py)")

    print("\n=== TEST 6: attendance_engine.recompute_day source ===")
    try:
        print(inspect.getsource(ae.recompute_day)[:800])
    except AttributeError:
        # try alternate names
        for name in ("_recompute_day", "compute_day", "_compute_day"):
            if hasattr(ae, name):
                print(f"  (using {name})")
                print(inspect.getsource(getattr(ae, name))[:800])
                break
        else:
            print("  no recompute_day found on attendance_engine")
finally:
    s.close()
    eng.dispose()