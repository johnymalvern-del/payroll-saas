"""Job B backend: add ?as_of= to GET /preview/{employee_id}.

- payroll_runner.py: through_date kwarg on _build_attendance_earnings and
  _build_all_earnings; new run_preview_for_employee_as_of() (pure read).
- payroll_pay_periods.py: as_of query param on the route; branch to new fn.
- payroll_pay_periods_schemas.py: 3 additive fields on PreviewEmployeeOut.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BE = ROOT / "backend"

# ============================================================
# 1. payroll_runner.py
# ============================================================
runner = BE / "app" / "services" / "payroll_runner.py"
s = runner.read_text(encoding="utf-8")

if "from datetime import" not in s:
    anchor = "import uuid\n"
    if anchor in s:
        s = s.replace(anchor, anchor + "from datetime import date\n", 1)
        print("runner: added `from datetime import date`")
elif not re.search(r"^from datetime import.*\bdate\b", s, re.M):
    s = s.replace(
        "from datetime import ",
        "from datetime import date, ",
        1,
    )
    print("runner: added `date` to datetime import")

# --- _build_attendance_earnings: signature + day-filter ---
old_sig = (
    "def _build_attendance_earnings(\n"
    "    db: Session,\n"
    "    employee: Employee,\n"
    "    pay_period: PayPeriod,\n"
    ") -> tuple[list[P.EarningLine], list[str], dict]:\n"
)
new_sig = (
    "def _build_attendance_earnings(\n"
    "    db: Session,\n"
    "    employee: Employee,\n"
    "    pay_period: PayPeriod,\n"
    "    through_date: date | None = None,\n"
    ") -> tuple[list[P.EarningLine], list[str], dict]:\n"
)
if old_sig in s:
    s = s.replace(old_sig, new_sig, 1)
    print("runner: _build_attendance_earnings signature extended")
elif "through_date" in s:
    print("runner: _build_attendance_earnings already has through_date")
else:
    raise SystemExit("FATAL: _build_attendance_earnings signature not matched")

# --- filter days by through_date after the query ---
old_days = "    days = list(db.scalars(\n        select(AttendanceDay).where(\n            AttendanceDay.employee_id == employee.id,\n            AttendanceDay.work_date >= pay_period.start_date,\n            AttendanceDay.work_date <= pay_period.end_date,\n        )\n    ).all())\n"
new_days = old_days + (
    "    if through_date is not None:\n"
    "        days = [d for d in days if d.work_date <= through_date]\n"
)
if old_days in s and "through_date is not None" not in s:
    s = s.replace(old_days, new_days, 1)
    print("runner: attendance days filtered by through_date")
elif "through_date is not None" in s:
    print("runner: through_date filter already present")
else:
    raise SystemExit("FATAL: attendance day query not matched")

# --- _build_all_earnings: signature + delegation ---
old_all = (
    "def _build_all_earnings(\n"
    "    db: Session, employee: Employee, pay_period: PayPeriod,\n"
    ") -> tuple[list[P.EarningLine], list[str], dict]:\n"
    "    fixed = _build_fixed_earnings(db, employee, pay_period.pay_date)\n"
    "    attn, warnings, snapshot = _build_attendance_earnings(db, employee, pay_period)\n"
    "    return fixed + attn, warnings, snapshot\n"
)
new_all = (
    "def _build_all_earnings(\n"
    "    db: Session, employee: Employee, pay_period: PayPeriod,\n"
    "    through_date: date | None = None,\n"
    ") -> tuple[list[P.EarningLine], list[str], dict]:\n"
    "    fixed = _build_fixed_earnings(db, employee, pay_period.pay_date)\n"
    "    attn, warnings, snapshot = _build_attendance_earnings(\n"
    "        db, employee, pay_period, through_date=through_date,\n"
    "    )\n"
    "    return fixed + attn, warnings, snapshot\n"
)
if old_all in s:
    s = s.replace(old_all, new_all, 1)
    print("runner: _build_all_earnings signature + delegation updated")
elif "through_date=through_date" in s:
    print("runner: _build_all_earnings already updated")
else:
    raise SystemExit("FATAL: _build_all_earnings not matched")

# --- new run_preview_for_employee_as_of ---
if "def run_preview_for_employee_as_of" not in s:
    s = s.rstrip() + '''


def run_preview_for_employee_as_of(
    db: Session,
    user,
    pay_period: PayPeriod,
    employee: Employee,
    as_of: date,
) -> dict:
    """Read-only payslip-so-far for one employee, up to `as_of`.

    No PayrollRun row, no Payslip row, no audit, no preview purge.
    Refuses locked periods (409). Monthly salaried refused with typed
    reason until the proration rule is confirmed (see §10).
    """
    if pay_period.status == "locked":
        raise AppError(
            "period_locked",
            "Cannot preview a finalised period; reopen it first",
            409,
        )
    if as_of < pay_period.start_date:
        raise AppError(
            "as_of_before_period_start",
            f"as_of ({as_of.isoformat()}) is before period start "
            f"({pay_period.start_date.isoformat()})",
            422,
        )
    if as_of > pay_period.end_date:
        as_of = pay_period.end_date

    base = {
        "employee_id": employee.id,
        "employee_code": employee.employee_code,
        "employee_name": f"{employee.first_name} {employee.last_name}".strip(),
        "pay_period_id": pay_period.id,
        "revision": None,
        "status": "as_of",
        "as_of": as_of,
        "gross": None,
        "paye": None,
        "net": None,
        "warnings": [],
        "lines": [],
        "deductions": [],
        "available": False,
        "reason_unavailable": None,
    }

    if employee.pay_basis not in ("hourly", "daily"):
        base["reason_unavailable"] = "monthly_proration_pending"
        return base

    config = build_pipeline_config(db, employee, pay_period.pay_date)
    earnings, attn_warnings, attn_snapshot = _build_all_earnings(
        db, employee, pay_period, through_date=as_of,
    )
    deductions = _build_deductions(db, employee, as_of)
    draft = P.run_pipeline(config, earnings, deductions, [])
    if draft.refused:
        base["reason_unavailable"] = draft.refusal_code or "compute_refused"
        base["warnings"] = list(attn_warnings) + [
            draft.refusal_message or "",
        ]
        return base

    base["available"] = True
    base["gross"] = draft.gross
    base["paye"] = draft.paye
    base["net"] = draft.net
    base["warnings"] = list(attn_warnings)
    base["lines"] = [
        {
            "earning_type_code": (
                ln.source_ref.get("earning_type_code", "")
                if ln.source_ref else ""
            ),
            "earning_type_name": ln.label,
            "rate_source": (
                "attendance"
                if ln.source_ref and ln.source_ref.get("attendance_derived")
                else "fixed"
            ),
            "amount": ln.amount,
            "minutes": (
                ln.source_ref.get("minutes")
                if ln.source_ref else None
            ),
        }
        for ln in earnings
    ]
    base["deductions"] = [
        {
            "deduction_type_code": getattr(d, "code", "") or "",
            "deduction_type_name": getattr(d, "label", "") or "",
            "amount": d.amount,
        }
        for d in deductions
    ]
    return base
'''
    runner.write_text(s, encoding="utf-8")
    print("runner: run_preview_for_employee_as_of appended")
else:
    print("runner: run_preview_for_employee_as_of already present")

# ============================================================
# 2. payroll_pay_periods.py — add as_of param + branch
# ============================================================
router_file = BE / "app" / "api" / "v1" / "payroll_pay_periods.py"
s = router_file.read_text(encoding="utf-8")

if "from datetime import date" not in s:
    anchor = "import uuid\n"
    if anchor in s:
        s = s.replace(anchor, anchor + "from datetime import date\n", 1)
        print("router: added `from datetime import date`")

if "run_preview_for_employee_as_of" not in s:
    s = s.replace(
        "from app.services.payroll_runner import finalise, reopen, run_preview\n",
        "from app.services.payroll_runner import (\n"
        "    finalise,\n"
        "    reopen,\n"
        "    run_preview,\n"
        "    run_preview_for_employee_as_of,\n"
        ")\n",
        1,
    )
    print("router: import added")

# add _preview_as_of helper before the route handler
if "def _preview_as_of(" not in s:
    helper = '''def _preview_as_of(db, user, period_id, employee_id, as_of: date) -> PreviewEmployeeOut:
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
    data = run_preview_for_employee_as_of(db, user, pay_period, employee, as_of)
    return PreviewEmployeeOut(**data)


'''
    # insert before `@router.get("/{period_id}/preview/{employee_id}"`
    anchor_route = '@router.get("/{period_id}/preview/{employee_id}", response_model=PreviewEmployeeOut)'
    if anchor_route not in s:
        raise SystemExit("FATAL: preview route anchor not found")
    s = s.replace(anchor_route, helper + anchor_route, 1)
    print("router: _preview_as_of helper inserted")

# find handler signature up to `) -> PreviewEmployeeOut:` and extend + branch
pat = re.compile(
    r'(@router\.get\("/\{period_id\}/preview/\{employee_id\}", response_model=PreviewEmployeeOut\)\n'
    r'def \w+\(\n'
    r'[^)]*)'  # everything up to but not including the closing )
    r'(\) -> PreviewEmployeeOut:\n)',
    re.MULTILINE,
)
m = pat.search(s)
if not m:
    raise SystemExit("FATAL: handler signature regex did not match — inspect before re-running")
if "as_of: date | None" in m.group(0):
    print("router: as_of already in handler signature")
else:
    new_block = (
        m.group(1)
        + "    as_of: date | None = Query(None),\n"
        + m.group(2)
        + "    if as_of is not None:\n"
        + "        return _preview_as_of(db, user, period_id, employee_id, as_of)\n"
    )
    s = s[:m.start()] + new_block + s[m.end():]
    print("router: handler extended with as_of param + branch")

router_file.write_text(s, encoding="utf-8")

# ============================================================
# 3. payroll_pay_periods_schemas.py — 3 fields on PreviewEmployeeOut
# ============================================================
schema_file = BE / "app" / "api" / "v1" / "payroll_pay_periods_schemas.py"
s = schema_file.read_text(encoding="utf-8")

if "from datetime import date" not in s:
    anchor = "from __future__ import annotations\n"
    if anchor in s:
        s = s.replace(anchor, anchor + "\nfrom datetime import date\n", 1)
        print("schema: added `from datetime import date`")

# find PreviewEmployeeOut and add 3 fields after the last field
pat = re.compile(
    r"(class PreviewEmployeeOut\(BaseModel\):.*?)(\n\nclass |\Z)",
    re.S,
)
m = pat.search(s)
if not m:
    raise SystemExit("FATAL: PreviewEmployeeOut class not found")
body = m.group(1)
if "available: bool" in body:
    print("schema: PreviewEmployeeOut already has available")
else:
    extras = (
        "\n    available: bool = True"
        "\n    reason_unavailable: str | None = None"
        "\n    as_of: date | None = None"
    )
    new_body = body.rstrip() + extras
    s = s[:m.start(1)] + new_body + s[m.end(1):]
    print("schema: PreviewEmployeeOut extended with 3 fields")

schema_file.write_text(s, encoding="utf-8")

print("\nJob B backend patch complete.")