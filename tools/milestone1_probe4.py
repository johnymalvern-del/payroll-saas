"""Milestone 1 — probe #4. Read-only source + SQL.

Answers the three remaining blockers:
- Is the tax/statutory pipeline self-bootstrapping, or does it need seed data?
- Why is recompute_day producing 0 segments on T001?
- What is the minimum demo-able employee?
"""
import inspect
import sys
from pathlib import Path
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

from app.services import payroll_runner as pr
from app.db.tenant.models.attendance import AttendanceSegment
from app.db.tenant.models.organisation import Company

# ---- 1. _ensure_bootstrapped source ----
print("=== 1. _ensure_bootstrapped SOURCE ===")
try:
    print(inspect.getsource(pr._ensure_bootstrapped))
except AttributeError:
    print("  NOT FOUND on payroll_runner")
    for mod_name in ("app.payroll_engine.tax", "app.services.tax_tables"):
        try:
            mod = __import__(mod_name, fromlist=["x"])
            for attr in dir(mod):
                if "ensure" in attr.lower() and "boot" in attr.lower():
                    print(f"  Found in {mod_name}: {attr}")
        except ImportError:
            pass

# ---- 2. load_tax_tables — refusal conditions ----
print("\n=== 2. load_tax_tables SOURCE (or refusal rules) ===")
try:
    from app.payroll_engine import tax as T
    print(inspect.getsource(T.load_tax_tables)[:2000])
except Exception as e:
    print(f"  Could not import tax module: {e}")
    # Try alternate path
    try:
        from app.payroll_engine import tax_tables as TT
        for name in ("load_tax_tables", "ensure_bootstrap"):
            fn = getattr(TT, name, None)
            if fn:
                print(f"  === {name} ===")
                print(inspect.getsource(fn)[:1500])
    except Exception as e2:
        print(f"  Alternate path failed: {e2}")

# ---- 3. Tenant-side checks ----
eng = create_engine(TENANT_URL)
s = Session(eng)
try:
    print("\n=== 3. Company row ===")
    c = s.scalar(select(Company))
    if c is None:
        print("  COMPANY: NONE (this is why some things may fail)")
    else:
        print(f"  company exists: id={c.id} country={c.country_code} tz={c.default_timezone}")

    print("\n=== 4. shift_rate_rule count ===")
    from app.db.tenant.models.attendance import ShiftRateRule
    n = s.scalar(select(func.count()).select_from(ShiftRateRule))
    print(f"  shift_rate_rule rows: {n}")

    print("\n=== 5. T001's attendance days without segments — WHY ===")
    from app.db.tenant.models.people import Employee
    from app.db.tenant.models.attendance import AttendanceDay, Shift
    t001 = s.scalar(select(Employee).where(Employee.employee_code == "T001"))
    if t001:
        days = s.scalars(
            select(AttendanceDay).where(AttendanceDay.employee_id == t001.id)
        ).all()
        print(f"  T001 has {len(days)} attendance_days")
        for d in days:
            segs = s.scalars(
                select(AttendanceSegment).where(AttendanceSegment.attendance_day_id == d.id)
            ).all()
            shift = s.get(Shift, d.shift_id) if d.shift_id else None
            shift_name = shift.name if shift else "(none)"
            print(f"    {d.work_date} status={d.status} shift={shift_name} "
                  f"segments={len(segs)}")
            if shift:
                rules = s.scalars(
                    select(ShiftRateRule).where(ShiftRateRule.shift_id == shift.id)
                ).all()
                print(f"      shift rate rules for '{shift_name}': {len(rules)}")
                for r in rules:
                    print(f"        {r.day_type}/{r.kind}/tier{r.tier} "
                          f"method={r.method} value={r.value} "
                          f"from={r.effective_from} to={r.effective_to}")
finally:
    s.close()
    eng.dispose()

# ---- 6. Control DB — does it have any rows now? ----
print("\n=== 6. Control DB — statutory_table count (recheck) ===")
ceng = create_engine(CONTROL_URL)
cs = Session(ceng)
try:
    for tbl in ("statutory_table", "country_profile", "public_holiday"):
        try:
            n = cs.execute(text(f'SELECT COUNT(*) FROM "{tbl}"')).scalar()
            print(f"  {tbl}: {n}")
        except Exception as e:
            print(f"  {tbl}: table error {e}")
finally:
    cs.close()
    ceng.dispose()