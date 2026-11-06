"""Add the missing _preview_as_of helper to payroll_pay_periods.py.

The route handler branch `if as_of is not None: return _preview_as_of(...)`
was inserted by job_b_fix.py but the helper function definition itself was
never written. That is the NameError the full suite caught.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BE = ROOT / "backend"
P = BE / "app" / "api" / "v1" / "payroll_pay_periods.py"
s = P.read_text(encoding="utf-8")

if "def _preview_as_of(" in s:
    print("already present — no change")
else:
    route_anchor = '@router.get("/{period_id}/preview/{employee_id}", response_model=PreviewEmployeeOut)'
    if route_anchor not in s:
        raise SystemExit(f"FATAL: route anchor not found:\n{route_anchor}")

    helper = '''def _preview_as_of(
    db,
    user,
    period_id: uuid.UUID,
    employee_id: uuid.UUID,
    as_of: date,
) -> PreviewEmployeeOut:
    """Read-only payslip-so-far for one employee, as of `as_of`.

    Used by GET .../preview/{employee_id}?as_of=YYYY-MM-DD. Does not
    persist anything (no PayrollRun, no Payslip, no audit). Delegates to
    payroll_runner.run_preview_for_employee_as_of.
    """
    pay_period = db.get(PayPeriod, period_id)
    if pay_period is None:
        raise AppError("record_not_found", "Pay period not found", 404)
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise AppError("record_not_found", "Employee not found", 404)
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise AppError("record_not_found", "Employee not found", 404) from None
    data = run_preview_for_employee_as_of(
        db, user, pay_period, employee, as_of,
    )
    return PreviewEmployeeOut(**data)


'''
    s = s.replace(route_anchor, helper + route_anchor, 1)
    P.write_text(s, encoding="utf-8")
    print("inserted _preview_as_of helper before the route decorator")