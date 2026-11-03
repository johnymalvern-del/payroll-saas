"""Add days/steps relationships to LeaveRequest; rewrite _rebuild_days via collection."""
import re
from pathlib import Path

MODEL = Path(__file__).resolve().parent.parent / "backend" / "app" / "db" / "tenant" / "models" / "leave.py"
ROUTER = Path(__file__).resolve().parent.parent / "backend" / "app" / "api" / "v1" / "leave_requests.py"

# ---------- leave.py: import relationship + add days/steps ----------
src = MODEL.read_text(encoding="utf-8")

if "from sqlalchemy.orm import relationship" not in src:
    idx = src.find("from sqlalchemy import (")
    assert idx >= 0, "sqlalchemy import anchor not found"
    end = src.find(")\n", idx)
    assert end > 0, "closing paren of sqlalchemy import not found"
    src = src[:end + 2] + "from sqlalchemy.orm import relationship\n" + src[end + 2:]
    print("leave.py: added relationship import")

if "days: Mapped[list]" not in src:
    lr_start = src.find("class LeaveRequest(Base):")
    assert lr_start >= 0, "LeaveRequest class not found"
    lr_day_start = src.find("class LeaveRequestDay(Base):", lr_start)
    assert lr_day_start > lr_start, "LeaveRequestDay class not found after LeaveRequest"
    insert_at = lr_day_start
    while insert_at > lr_start and src[insert_at - 1] == "\n":
        insert_at -= 1
    inject = """
    days: Mapped[list] = relationship(
        "LeaveRequestDay", cascade="all, delete-orphan", lazy="selectin",
        order_by="LeaveRequestDay.work_date",
    )
    steps: Mapped[list] = relationship(
        "LeaveApprovalStep", cascade="all, delete-orphan", lazy="selectin",
        order_by="LeaveApprovalStep.step_no",
    )
"""
    src = src[:insert_at] + inject + src[insert_at:]
    print("leave.py: added days/steps relationships to LeaveRequest")

MODEL.write_text(src, encoding="utf-8")

# ---------- leave_requests.py: rewrite _rebuild_days via relationship ----------
r = ROUTER.read_text(encoding="utf-8")

pat = re.compile(
    r"def _rebuild_days\(\s*db: Any, request: LeaveRequest,\s*\) -> "
    r"list\[LeaveRequestDay\]:.*?\n    return new_rows\n",
    re.S,
)
match = pat.search(r)
assert match, "_rebuild_days not found"

new_rebuild = '''def _rebuild_days(
    db: Any, request: LeaveRequest,
) -> list[LeaveRequestDay]:
    employee = db.get(Employee, request.employee_id)
    if employee is None:
        raise AppError("not_found", "Employee not found", 404)
    computed = compute_request_days(
        db, employee, request.from_date, request.to_date
    )
    if not computed:
        raise AppError(
            "no_working_days_in_range",
            "The date range has no working days for this employee",
            422,
        )
    request.days.clear()
    db.flush()
    for wd, days in computed:
        request.days.append(LeaveRequestDay(work_date=wd, days=days))
    request.days_requested = sum((d for _, d in computed), _zero())
    db.flush()
    return list(request.days)
'''
r = r[:match.start()] + new_rebuild + r[match.end():]
ROUTER.write_text(r, encoding="utf-8")
print("leave_requests.py: rewrote _rebuild_days via request.days collection")