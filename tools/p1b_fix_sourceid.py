"""Fix: source_id needs a default of None in create_decision_record signature."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "backend" / "app" / "services" / "intelligence_service.py"
s = P.read_text(encoding="utf-8")

old = "    source_id: uuid.UUID | None,\n"
new = "    source_id: uuid.UUID | None = None,\n"
if old not in s:
    if new in s:
        print("already has default")
    else:
        raise SystemExit("FATAL: `source_id` line not found")
else:
    s = s.replace(old, new, 1)
    P.write_text(s, encoding="utf-8")
    print("patched: source_id: uuid.UUID | None = None")