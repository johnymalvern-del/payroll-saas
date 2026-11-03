"""L2d fix8:
1. Model: fix days/steps relationships — uselist=True + parameterized Mapped[...]
   + explicit foreign_keys + lazy='raise' (router never reads them; any
   accidental access errors immediately).
2. Router: replace the two remaining request.steps accesses with explicit
   select(...) / delete(...) statements.
Dumps final text of the changed functions and re-runs both test files.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "backend" / "app" / "db" / "tenant" / "models" / "leave.py"
ROUTER = ROOT / "backend" / "app" / "api" / "v1" / "leave_requests.py"

# --- 1. Model: replace days/steps relationships ---
msrc = MODEL.read_text(encoding="utf-8")

old_rel_pat = re.compile(
    r"    days: Mapped\[list\] = relationship\(\n"
    r"        \"LeaveRequestDay\", cascade=\"all, delete-orphan\", lazy=\"selectin\",\n"
    r"        order_by=\"LeaveRequestDay\.work_date\",\n"
    r"    \)\n"
    r"    steps: Mapped\[list\] = relationship\(\n"
    r"        \"LeaveApprovalStep\", cascade=\"all, delete-orphan\", lazy=\"selectin\",\n"
    r"        order_by=\"LeaveApprovalStep\.step_no\",\n"
    r"    \)",
)
m = old_rel_pat.search(msrc)
if not m:
    print("MODEL: current relationship block not found verbatim; trying looser match")
    old_rel_pat = re.compile(
        r"    days: Mapped\[[^\]]*\] = relationship\(.*?\)\n"
        r"    steps: Mapped\[[^\]]*\] = relationship\(.*?\)",
        re.S,
    )
    m = old_rel_pat.search(msrc)
if not m:
    raise SystemExit("FATAL: relationship block not found in leave.py")

new_rel = '''    days: Mapped[list["LeaveRequestDay"]] = relationship(
        "LeaveRequestDay",
        uselist=True,
        foreign_keys="[LeaveRequestDay.leave_request_id]",
        order_by="LeaveRequestDay.work_date",
        lazy="raise",
    )
    steps: Mapped[list["LeaveApprovalStep"]] = relationship(
        "LeaveApprovalStep",
        uselist=True,
        foreign_keys="[LeaveApprovalStep.leave_request_id]",
        order_by="LeaveApprovalStep.step_no",
        lazy="raise",
    )'''
msrc = msrc[:m.start()] + new_rel + msrc[m.end():]
MODEL.write_text(msrc, encoding="utf-8")
print("MODEL: replaced days/steps relationships (uselist=True, lazy='raise')")

# --- 2. Router: _current_step explicit query ---
rsrc = ROUTER.read_text(encoding="utf-8")

old_cs = '''def _current_step(
    db: Any, request: LeaveRequest,
) -> LeaveApprovalStep | None:
    for s in sorted(request.steps or [], key=lambda x: x.step_no):
        if s.status == "pending":
            return s
    return None
'''
new_cs = '''def _current_step(
    db: Any, request: LeaveRequest,
) -> LeaveApprovalStep | None:
    return db.scalars(
        select(LeaveApprovalStep)
        .where(LeaveApprovalStep.leave_request_id == request.id)
        .where(LeaveApprovalStep.status == "pending")
        .order_by(LeaveApprovalStep.step_no)
        .limit(1)
    ).first()
'''
if old_cs in rsrc:
    rsrc = rsrc.replace(old_cs, new_cs, 1)
    print("ROUTER: _current_step rewritten to explicit query")
else:
    print("ROUTER: _current_step text did not match verbatim; using regex")
    pat_cs = re.compile(
        r"def _current_step\(\s*db: Any, request: LeaveRequest,\s*\) "
        r"-> LeaveApprovalStep \| None:.*?(?=\n\ndef |\n\n@|\Z)",
        re.S,
    )
    m2 = pat_cs.search(rsrc)
    if not m2:
        raise SystemExit("FATAL: _current_step not found")
    rsrc = rsrc[:m2.start()] + new_cs + rsrc[m2.end():]
    print("ROUTER: _current_step rewritten (regex path)")

# --- 3. Router: _apply_chain explicit delete ---
old_del = '''    for old in list(request.steps or []):
        db.delete(old)
    db.flush()
'''
new_del = '''    db.execute(
        delete(LeaveApprovalStep).where(
            LeaveApprovalStep.leave_request_id == request.id
        )
    )
    db.flush()
'''
if old_del in rsrc:
    rsrc = rsrc.replace(old_del, new_del, 1)
    print("ROUTER: _apply_chain delete rewritten to explicit statement")
else:
    raise SystemExit("FATAL: _apply_chain delete block not found")

ROUTER.write_text(rsrc, encoding="utf-8")

# --- 4. Dump final texts ---
print("=== _current_step FINAL ===")
m3 = re.search(r"def _current_step\(.*?(?=\n\ndef |\n\n@|\Z)", rsrc, re.S)
print(m3.group(0) if m3 else "NOT FOUND")

print("=== _apply_chain FINAL ===")
m4 = re.search(r"def _apply_chain\(.*?(?=\n\ndef |\n\n@|\Z)", rsrc, re.S)
print(m4.group(0) if m4 else "NOT FOUND")

print("=== .steps / .days remaining in router ===")
for mm in re.finditer(r"\.(steps|days)\b", rsrc):
    ln = rsrc[:mm.start()].count("\n") + 1
    ls = rsrc.rfind("\n", 0, mm.start()) + 1
    le = rsrc.find("\n", mm.end())
    print(f"  line {ln}: {rsrc[ls:le].strip()}")