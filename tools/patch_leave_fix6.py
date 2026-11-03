"""L2d fix6:
1. compute_request_days: (a) tuple-return bug — `if tuple:` was always True;
   use `[0]`. (b) if employee has no work pattern at all, return [].
2. test_leave_requests.py::_mk_type: requires_payroll_admin_final=True so
   submission with only the payroll_admin user present resolves a chain.
Dumps final text of _commit_or_map and _rebuild_days, plus `session` fixture
from both test files, and lists seed test files for the next bundle.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEAVE_ENGINE = ROOT / "backend" / "app" / "payroll_engine" / "leave.py"
ROUTER = ROOT / "backend" / "app" / "api" / "v1" / "leave_requests.py"
T1 = ROOT / "backend" / "tests" / "test_leave_requests.py"
T2 = ROOT / "backend" / "tests" / "test_leave_approval.py"

# --- 1. compute_request_days rewrite ---
src = LEAVE_ENGINE.read_text(encoding="utf-8")
pat = re.compile(
    r"def compute_request_days\(\s*db: Session,\s*employee: Employee,\s*"
    r"from_date: date,\s*to_date: date,\s*\) -> list\[tuple\[date, Decimal\]\]:"
    r".*?(?=\n\ndef |\n\n#|\Z)",
    re.S,
)
m = pat.search(src)
if not m:
    raise SystemExit("FATAL: compute_request_days not found")
new_fn = '''def compute_request_days(
    db: Session,
    employee: Employee,
    from_date: date,
    to_date: date,
) -> list[tuple[date, Decimal]]:
    from app.api.v1.attendance_engine import _employee_expected
    from app.db.tenant.models.attendance import EmployeeWorkPattern

    has_wp = getattr(employee, "work_pattern_id", None) is not None
    if not has_wp:
        ewp_id = db.scalar(
            select(EmployeeWorkPattern.id)
            .where(EmployeeWorkPattern.employee_id == employee.id)
            .limit(1)
        )
        has_wp = ewp_id is not None
    if not has_wp:
        return []

    out: list[tuple[date, Decimal]] = []
    cur = from_date
    while cur <= to_date:
        if _employee_expected(db, employee, cur)[0]:
            out.append((cur, Decimal("1")))
        cur += timedelta(days=1)
    return out
'''
src = src[:m.start()] + new_fn + src[m.end():]
LEAVE_ENGINE.write_text(src, encoding="utf-8")
print("patched compute_request_days")

# --- 2. test_leave_requests.py::_mk_type default ---
t1 = T1.read_text(encoding="utf-8")
old = '''        approval_chain=["manager", "hr"],
        requires_payroll_admin_final=False,
'''
new = '''        approval_chain=["manager", "hr"],
        requires_payroll_admin_final=True,
'''
n = t1.count(old)
if n != 1:
    raise SystemExit(f"FATAL: _mk_type default not found (count={n})")
t1 = t1.replace(old, new, 1)
T1.write_text(t1, encoding="utf-8")
print("patched _mk_type in test_leave_requests.py")

# --- 3. Dump _commit_or_map and _rebuild_days ---
r = ROUTER.read_text(encoding="utf-8")
def dump_fn(name):
    m2 = re.search(rf"def {name}\(.*?(?=\n\ndef |\n\n@|\Z)", r, re.S)
    print(f"=== {name} FINAL ===")
    print(m2.group(0) if m2 else "NOT FOUND")
dump_fn("_commit_or_map")
dump_fn("_rebuild_days")

# --- 4. Probe session fixture from both test files ---
for tp in (T1, T2):
    c = tp.read_text(encoding="utf-8")
    print(f"=== {tp.name} session fixture ===")
    m3 = re.search(
        r"(@pytest\.fixture[^\n]*\n(?:@[^\n]*\n)*)?def session\([^)]*\).*?(?=\n\ndef |\n\n@pytest\.fixture|\Z)",
        c, re.S,
    )
    if m3:
        print(m3.group(0)[:5000])
    else:
        print("NOT FOUND - first 120 lines:")
        print("\n".join(c.split("\n")[:120]))

# --- 5. Seed test files (first 100 lines each) ---
print("=== seed test files ===")
for p in sorted((ROOT / "backend" / "tests").glob("test_seed*.py")):
    print(f"--- {p.name} first 100 lines ---")
    print("\n".join(p.read_text(encoding="utf-8").split("\n")[:100]))