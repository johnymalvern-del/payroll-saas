"""L2d fix: pre-compute days_requested before insert; map IntegrityError -> AppError on this router."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "backend" / "app" / "api" / "v1" / "leave_requests.py"
src = P.read_text(encoding="utf-8")

anchor = "def _rebuild_days(\n"
helper = '''from sqlalchemy.exc import IntegrityError


def _extract_constraint(msg: str) -> str | None:
    marker = 'constraint "'
    i = msg.find(marker)
    if i < 0:
        return None
    j = msg.find('"', i + len(marker))
    return msg[i + len(marker):j] if j > 0 else None


def _commit_or_map(db: Any) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            "integrity_violation",
            "Request violates a database constraint",
            422,
            {"constraint": _extract_constraint(str(exc))},
        ) from exc


'''
assert src.count(anchor) == 1, f"_rebuild_days anchor count = {src.count(anchor)}"
src = src.replace(anchor, helper + anchor, 1)

n_commits = src.count("    db.commit()")
assert n_commits >= 7, f"expected >=7 db.commit(), found {n_commits}"
src = src.replace("    db.commit()", "    _commit_or_map(db)")

old_create = '''    employee = _load_employee(db, user, employee_id)
    lt = _load_leave_type(db, body.leave_type_id)

    request = LeaveRequest(
        employee_id=employee.id,
        leave_type_id=lt.id,
        from_date=body.from_date,
        to_date=body.to_date,
        days_requested=_zero(),
'''
new_create = '''    employee = _load_employee(db, user, employee_id)
    lt = _load_leave_type(db, body.leave_type_id)

    computed = compute_request_days(db, employee, body.from_date, body.to_date)
    if not computed:
        raise AppError(
            "no_working_days_in_range",
            "The date range has no working days for this employee",
            422,
        )
    days_total = sum((d for _, d in computed), _zero())

    request = LeaveRequest(
        employee_id=employee.id,
        leave_type_id=lt.id,
        from_date=body.from_date,
        to_date=body.to_date,
        days_requested=days_total,
'''
assert src.count(old_create) == 1, f"create anchor count = {src.count(old_create)}"
src = src.replace(old_create, new_create, 1)

P.write_text(src, encoding="utf-8")
print(f"patched leave_requests.py; db.commit() sites wrapped = {n_commits}")