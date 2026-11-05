"""L2d fix: make _backfill_exceptions collision-safe with engine-created
open exceptions. Root cause: seed blindly inserts 16 open ExceptionItem
rows, but the attendance engine already created some during recompute,
violating the partial unique index uq_exception_item_open on
(employee_id, work_date, type) WHERE status='open'.

Fix: pre-query existing open-exception keys; skip a candidate cell on
collision and retry with the next rotation slot (cap 10 attempts per
required placement, still aiming for 2 per type). Preserves demo intent
and honours the DB-level invariant.
"""
import re
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "backend" / "app" / "seed" / "demo_seed.py"
src = P.read_text(encoding="utf-8")

# ---- 1. Ensure `select` is imported at module level ----
if re.search(r"^\s*from sqlalchemy import[^\n]*\bselect\b", src, re.M):
    print("demo_seed: `select` already imported")
else:
    m = re.search(r"from sqlalchemy import \(([^)]*)\)", src, re.S)
    if m:
        src = src[:m.start(1)] + "select, " + m.group(1) + src[m.end(1):]
        print("demo_seed: added `select` (paren import)")
    else:
        m = re.search(r"from sqlalchemy import ([^\n(]+)", src)
        if m:
            src = src[:m.start(1)] + "select, " + m.group(1) + src[m.end(1):]
            print("demo_seed: added `select` (line import)")
        else:
            raise SystemExit("FATAL: no sqlalchemy import line found")

# ---- 2. Replace _backfill_exceptions ----
pat = re.compile(
    r"def _backfill_exceptions\(\n"
    r"    db, employees: list\[Employee\], start_date: date,\n"
    r"\) -> None:\n.*?db\.commit\(\)\n",
    re.S,
)
m = pat.search(src)
if not m:
    raise SystemExit("FATAL: _backfill_exceptions body not found")

new_fn = '''def _backfill_exceptions(
    db, employees: list[Employee], start_date: date,
) -> None:
    types_missing = [
        "missing_in", "low_confidence", "overtime_unapproved",
        "duplicate", "device_clock_gap", "employee_query",
        "absent_expected", "too_long",
    ]
    # Skip any cell whose (employee, work_date, type) is already open —
    # the attendance engine creates open exceptions during recompute and
    # uq_exception_item_open forbids duplicates.
    existing: set[tuple] = {
        (eid, d, t) for eid, d, t in db.execute(
            select(
                ExceptionItem.employee_id,
                ExceptionItem.work_date,
                ExceptionItem.type,
            ).where(ExceptionItem.status == "open")
        ).all()
    }
    idx = 0
    for t in types_missing:
        placed = 0
        attempts = 0
        while placed < 2 and attempts < 10:
            emp = employees[idx % len(employees)]
            d = start_date + timedelta(days=idx % 10)
            key = (emp.id, d, t)
            idx += 1
            attempts += 1
            if key in existing:
                continue
            existing.add(key)
            db.add(ExceptionItem(
                id=uuid.uuid4(),
                employee_id=emp.id,
                work_date=d,
                type=t,
                source_ref={"seed": True},
                suggested_fix={},
                status="open",
            ))
            placed += 1
    db.commit()
'''
src = src[:m.start()] + new_fn + src[m.end():]
P.write_text(src, encoding="utf-8")
print("demo_seed: _backfill_exceptions rewritten (collision-safe)")