"""Milestone 1 — pre-seed inspection of tenant_tenant_demo. Read-only.

Prints exactly what exists so the seed plan uses real data and does not
assume any state.
"""
import sys
from pathlib import Path
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

URL = (
    "postgresql+psycopg://payroll_test:payroll_test_dev_password"
    "@localhost:5432/tenant_tenant_demo"
)

from app.db.tenant.models.people import Employee, User
from app.db.tenant.models.pay import (
    PayPeriod, PayrollRun, Payslip, EarningType, DeductionType,
)
from app.db.tenant.models.attendance import AttendanceDay
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.intelligence import IntelligenceSettings
from app.services import payroll_runner
import inspect

eng = create_engine(URL)
s = Session(eng)
try:
    print("=== USERS ===")
    for u in s.scalars(select(User).order_by(User.username)):
        print(
            f"  {u.username:25} role={u.role:15} "
            f"employee_id={u.employee_id} active={u.is_active}"
        )

    total_emps = s.scalar(select(func.count()).select_from(Employee))
    print(f"\n=== EMPLOYEES ({total_emps} total) ===")
    for e in s.scalars(select(Employee).order_by(Employee.employee_code).limit(30)):
        print(
            f"  {e.employee_code:8} {e.first_name:12} {e.last_name:12} "
            f"status={e.status:10} pay_basis={e.pay_basis:8} "
            f"type={e.employee_type:8} base_rate={e.base_rate}"
        )

    print("\n=== PAY PERIODS ===")
    for p in s.scalars(select(PayPeriod).order_by(PayPeriod.start_date.desc())):
        runs = s.scalar(
            select(func.count()).select_from(PayrollRun)
            .where(PayrollRun.pay_period_id == p.id)
        )
        payslips = s.scalar(
            select(func.count()).select_from(Payslip)
            .where(Payslip.pay_period_id == p.id)
        )
        print(
            f"  {p.period_key:10} {p.start_date}..{p.end_date} "
            f"status={p.status:8} runs={runs} payslips={payslips} "
            f"cutoff={p.cutoff_at}"
        )

    print("\n=== PAYSLIPS ===")
    cnt = s.scalar(select(func.count()).select_from(Payslip))
    print(f"  Total payslips: {cnt}")
    if cnt:
        for ps in s.scalars(select(Payslip).limit(5)):
            print(
                f"    emp_id={ps.employee_id} period={ps.pay_period_id} "
                f"status={ps.status} rev={ps.revision} net={ps.net}"
            )

    print("\n=== PAYROLL SETTINGS ===")
    st = s.scalar(select(PayrollSettings).limit(1))
    if st:
        print(f"  demo_values: {st.demo_values}")
        print(f"  unpaid_day_behaviour: {st.unpaid_day_behaviour}")
        print(f"  unpaid_day_formula_code: {st.unpaid_day_formula_code}")
        print(
            f"  public_holiday_unworked_monthly: "
            f"{st.public_holiday_unworked_monthly}"
        )
        print(
            f"  monthly_hourly_derivation_formula_code: "
            f"{st.monthly_hourly_derivation_formula_code}"
        )
        print(f"  leave_authoritative_source: {st.leave_authoritative_source}")
        print(f"  attendance_earning_map: {st.attendance_earning_map}")
        print(f"  formula_acks keys: {list((st.formula_acks or {}).keys())}")
    else:
        print("  NO SETTINGS ROW")

    print("\n=== EARNING TYPES ===")
    for et in s.scalars(select(EarningType)):
        print(
            f"  {et.code:30} {et.name:30} freq={et.frequency} "
            f"taxable={et.is_taxable} uif={et.counts_for_uif} sdl={et.counts_for_sdl}"
        )

    print("\n=== DEDUCTION TYPES ===")
    for dt in s.scalars(select(DeductionType)):
        print(f"  {dt.code:30} {dt.name:30} freq={dt.frequency}")

    print("\n=== ATTENDANCE ROWS ===")
    cnt = s.scalar(select(func.count()).select_from(AttendanceDay))
    print(f"  Total attendance_days: {cnt}")
    if cnt:
        rng = s.execute(
            text("SELECT MIN(work_date), MAX(work_date) FROM attendance_day")
        ).first()
        print(f"  Date range: {rng}")

    print("\n=== INTELLIGENCE SETTINGS ===")
    for iset in s.scalars(select(IntelligenceSettings)):
        print(
            f"  id={iset.id} default_mode={iset.default_mode} "
            f"row_version={iset.row_version}"
        )
finally:
    s.close()
    eng.dispose()

print("\n=== _group_key_for_segment SOURCE ===")
print(inspect.getsource(payroll_runner._group_key_for_segment))

print("\n=== _formula_warnings SOURCE ===")
print(inspect.getsource(payroll_runner._formula_warnings))