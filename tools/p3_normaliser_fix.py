"""Fix P3 root cause: shift_id missing from DayOut type and normaliser.
Without it, day.data.shift_id is undefined at runtime and the Shift section
never renders even though the backend sends the field."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
api = ROOT / "frontend" / "src" / "api" / "attendance.ts"
s = api.read_text(encoding="utf-8")

# 1. DayOut type — add shift_id if not already there
dayout_match = re.search(r"export type DayOut = \{([\s\S]*?)\n\};", s)
if not dayout_match:
    raise SystemExit("FATAL: DayOut type not found")
dayout_body = dayout_match.group(1)

if "shift_id:" in dayout_body:
    print("DayOut: shift_id already present")
else:
    new_body = dayout_body.rstrip() + "\n  shift_id: string | null;"
    s = s[:dayout_match.start(1)] + new_body + s[dayout_match.end(1):]
    print("DayOut: shift_id added")

# 2. normaliseDayOut — add shift_id
norm_match = re.search(r"function normaliseDayOut\([\s\S]*?return \{([\s\S]*?)\n  \};\n\}", s)
if not norm_match:
    raise SystemExit("FATAL: normaliseDayOut return block not found")
norm_body = norm_match.group(1)

if "shift_id:" in norm_body:
    print("normaliseDayOut: shift_id already present")
else:
    new_norm = norm_body.rstrip() + (
        '\n    shift_id: typeof obj.shift_id === "string" ? obj.shift_id : null,'
    )
    s = s[:norm_match.start(1)] + new_norm + s[norm_match.end(1):]
    print("normaliseDayOut: shift_id added")

api.write_text(s, encoding="utf-8")
print("wrote attendance.ts")