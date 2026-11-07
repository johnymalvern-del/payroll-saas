"""Add module-level `from sqlalchemy import select, text` to the test file."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "backend" / "tests" / "test_intelligence_decision_records.py"
s = P.read_text(encoding="utf-8")

# Check existing top-level sqlalchemy imports
has_select = False
has_text = False
for ln in s.split("\n"):
    if ln.startswith("from sqlalchemy import"):
        if " select" in ln or ln.strip() == "from sqlalchemy import select":
            has_select = True
        if " text" in ln or ln.strip() == "from sqlalchemy import text":
            has_text = True

print(f"has_select(top-level)={has_select}  has_text(top-level)={has_text}")

if has_select and has_text:
    print("nothing to do")
else:
    # Find where `from sqlalchemy import text` currently sits (it must, since
    # test_snapshot_update_raises uses text). Extend to include select.
    target_old = "from sqlalchemy import text\n"
    target_new = "from sqlalchemy import select, text\n"
    if target_old in s and not has_select:
        s = s.replace(target_old, target_new, 1)
        P.write_text(s, encoding="utf-8")
        print("extended 'from sqlalchemy import text' -> 'select, text'")
    else:
        # Fall back: insert after the imports block
        anchor = "from sqlalchemy.orm import Session\n"
        if anchor not in s:
            raise SystemExit("FATAL: neither 'from sqlalchemy import text' nor "
                             "'from sqlalchemy.orm import Session' found")
        s = s.replace(anchor, anchor + target_new, 1)
        P.write_text(s, encoding="utf-8")
        print("inserted 'from sqlalchemy import select, text' after Session import")