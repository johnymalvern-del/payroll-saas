"""L2d fix4: eliminate ORM relationship access for leave days/steps.

Rewrites _rebuild_days, _to_out, and every .days / .steps usage in
leave_requests.py to use explicit SQLAlchemy queries. Reports every
remaining .days / .steps usage after patching, and dumps each test
file's first 90 lines (which contain the `session` fixture).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTER = ROOT / "backend" / "app" / "api" / "v1" / "leave_requests.py"
TEST1 = ROOT / "backend" / "tests" / "test_leave_requests.py"
TEST2 = ROOT / "backend" / "tests" / "test_leave_approval.py"

src = ROUTER.read_text(encoding="utf-8")

# ---- 0. Report .days / .steps BEFORE ----
print("=== .days / .steps BEFORE ===")
for m in re.finditer(r"\.(days|steps)\b", src):
    ln = src[:m.start()].count("\n") + 1
    ls = src.rfind("\n", 0, m.start()) + 1
    le = src.find("\n", m.end())
    print(f"  line {ln}: {src[ls:le if le > 0 else len(src)].strip()}")

# ---- 1. Ensure imports ----
def ensure_sa_import(name):
    global src
    m = re.search(r"from sqlalchemy import \(([^)]*)\)", src, re.S)
    if m:
        if re.search(rf"\b{name}\b", m.group(1)):
            return
        src = src[:m.start(1)] + f"{name}, " + m.group(1) + src[m.end(1):]
        print(f"import: added {name} (paren)")
        return
    m = re.search(r"from sqlalchemy import ([^\n(]+)", src)
    if m:
        if re.search(rf"\b{name}\b", m.group(1)):
            return
        src = src[:m.start(1)] + f"{name}, " + m.group(1) + src[m.end(1):]
        print(f"import: added {name} (line)")
        return
    raise SystemExit(f"FATAL: no sqlalchemy import for {name}")

ensure_sa_import("delete")
ensure_sa_import("select")

# ---- 2. Ensure LeaveRequestDayOut is imported ----
if "LeaveRequestDayOut" not in src:
    m = re.search(
        r"from app\.api\.v1\.leave_requests_schemas import \(([^)]*)\)",
        src, re.S,
    )
    if m:
        src = src[:m.start(1)] + "LeaveRequestDayOut, " + m.group(1) + src[m.end(1):]
        print("import: added LeaveRequestDayOut (paren)")
    else:
        m = re.search(
            r"from app\.api\.v1\.leave_requests_schemas import ([^\n(]+)",
            src,
        )
        if m:
            src = src[:m.start(1)] + "LeaveRequestDayOut, " + m.group(1) + src[m.end(1):]
            print("import: added LeaveRequestDayOut (line)")
        else:
            raise SystemExit("FATAL: cannot add LeaveRequestDayOut import")

# ---- 3. Rewrite _to_out ----
pat_to = re.compile(
    r"def _to_out\([^)]*\) -> LeaveRequestOut:.*?(?=\n\ndef |\n\n@|\Z)",
    re.S,
)
m_to = pat_to.search(src)
if not m_to:
    raise SystemExit("FATAL: _to_out not found")
print("=== _to_out BEFORE ===")
print(m_to.group(0))
new_to = '''def _to_out(db: Any, request: LeaveRequest) -> LeaveRequestOut:
    day_rows = db.scalars(
        select(LeaveRequestDay)
        .where(LeaveRequestDay.leave_request_id == request.id)
        .order_by(LeaveRequestDay.work_date)
    ).all()
    step_rows = db.scalars(
        select(LeaveApprovalStep)
        .where(LeaveApprovalStep.leave_request_id == request.id)
        .order_by(LeaveApprovalStep.step_no)
    ).all()
    data: dict = {}
    for name in LeaveRequestOut.model_fields:
        if name == "days":
            data[name] = [
                LeaveRequestDayOut.model_validate(d, from_attributes=True)
                for d in day_rows
            ]
        elif name == "steps":
            data[name] = [
                LeaveApprovalStepOut.model_validate(s, from_attributes=True)
                for s in step_rows
            ]
        else:
            data[name] = getattr(request, name, None)
    return LeaveRequestOut.model_validate(data)
'''
src = src[:m_to.start()] + new_to + src[m_to.end():]
print("rewrote _to_out")

# ---- 4. Update _to_out call sites ----
src = src.replace("_to_out(request)", "_to_out(db, request)")
src, n2 = re.subn(
    r"_to_out\((?!db,)([a-z_][a-z0-9_]*)\)",
    lambda m: f"_to_out(db, {m.group(1)})",
    src,
)
print(f"extra _to_out call sites updated: {n2}")

# ---- 5. Rewrite _rebuild_days ----
pat_rb = re.compile(
    r"def _rebuild_days\(\s*db: Any, request: LeaveRequest,\s*\) "
    r"-> list\[LeaveRequestDay\]:.*?(?=\n\ndef |\n\n@|\Z)",
    re.S,
)
m_rb = pat_rb.search(src)
if not m_rb:
    raise SystemExit("FATAL: _rebuild_days not found")
new_rb = '''def _rebuild_days(
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
    db.execute(
        delete(LeaveRequestDay).where(
            LeaveRequestDay.leave_request_id == request.id
        )
    )
    rows = [
        LeaveRequestDay(
            leave_request_id=request.id, work_date=wd, days=d,
        )
        for wd, d in computed
    ]
    db.add_all(rows)
    request.days_requested = sum((d for _, d in computed), _zero())
    db.flush()
    return rows
'''
src = src[:m_rb.start()] + new_rb + src[m_rb.end():]
print("rewrote _rebuild_days")

# ---- 6. In-endpoint usages ----
REPL = [
    (
        "days = list(request.days or [])",
        """days = list(db.scalars(
        select(LeaveRequestDay).where(
            LeaveRequestDay.leave_request_id == request.id
        )
    ))""",
    ),
    (
        "for d in (request.days or [])",
        """for d in db.scalars(
            select(LeaveRequestDay).where(
                LeaveRequestDay.leave_request_id == request.id
            )
        )""",
    ),
    (
        "steps = sorted(request.steps or [], key=lambda s: s.step_no)",
        """steps = list(db.scalars(
        select(LeaveApprovalStep)
        .where(LeaveApprovalStep.leave_request_id == request.id)
        .order_by(LeaveApprovalStep.step_no)
    ))""",
    ),
    (
        "[d.work_date for d in (request.days or [])]",
        """[d.work_date for d in db.scalars(
                select(LeaveRequestDay).where(
                    LeaveRequestDay.leave_request_id == request.id
                )
            )]""",
    ),
]
for old, new in REPL:
    if old in src:
        src = src.replace(old, new)
        print(f"replaced: {old[:60]}")

# ---- 7. Report AFTER ----
print("=== .days / .steps AFTER ===")
left = 0
for m in re.finditer(r"\.(days|steps)\b", src):
    ln = src[:m.start()].count("\n") + 1
    ls = src.rfind("\n", 0, m.start()) + 1
    le = src.find("\n", m.end())
    print(f"  line {ln}: {src[ls:le if le > 0 else len(src)].strip()}")
    left += 1
print(f"remaining: {left}")

print("=== _to_out call sites AFTER ===")
for m in re.finditer(r"_to_out\([^)]*\)", src):
    ln = src[:m.start()].count("\n") + 1
    print(f"  line {ln}: {m.group(0)}")

ROUTER.write_text(src, encoding="utf-8")
print("WROTE leave_requests.py")

# ---- 8. Dump session fixtures from each test file ----
for tp in (TEST1, TEST2):
    if not tp.exists():
        print(f"WARN: {tp} not found")
        continue
    c = tp.read_text(encoding="utf-8")
    print(f"=== {tp.name} first 90 lines ===")
    print("\n".join(c.split("\n")[:90]))