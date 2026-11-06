"""Fix two defects in payroll_pay_periods.py.

1. run_preview_for_employee_as_of is called but not imported.
2. as_of default is Query(None) instead of None, so direct-call tests
   receive the marker object and enter the as_of branch.
"""
import re
from pathlib import Path

BE = Path(__file__).resolve().parent.parent / "backend"
P = BE / "app" / "api" / "v1" / "payroll_pay_periods.py"
s = P.read_text(encoding="utf-8")

# Sanity: function exists in runner
runner = BE / "app" / "services" / "payroll_runner.py"
if "def run_preview_for_employee_as_of" not in runner.read_text(encoding="utf-8"):
    raise SystemExit(
        "FATAL: run_preview_for_employee_as_of not in payroll_runner.py — "
        "job_b_backend.py did not complete"
    )

# ---- Fix 1: import above the first helper ----
before_helper = s.split("def _preview_as_of", 1)[0]
already_imported = bool(
    re.search(r"\brun_preview_for_employee_as_of\b", before_helper)
)

if already_imported:
    print("import: already present above _preview_as_of helper")
else:
    m = re.search(
        r"from app\.services\.payroll_runner import \(([^)]*)\)\n",
        s,
    )
    if m:
        inner = m.group(1)
        if "run_preview_for_employee_as_of" in inner:
            print("import: already in multi-line block (unexpected position)")
        else:
            new_inner = inner.rstrip()
            if not new_inner.endswith(","):
                new_inner += ","
            new_inner += "\n    run_preview_for_employee_as_of,\n"
            s = (
                s[:m.start()]
                + f"from app.services.payroll_runner import ({new_inner})\n"
                + s[m.end():]
            )
            print("import: extended existing multi-line import block")
    else:
        m2 = re.search(
            r"from app\.services\.payroll_runner import ([^\n(]+)\n", s,
        )
        if not m2:
            raise SystemExit(
                "FATAL: could not find payroll_runner import in either form"
            )
        names = m2.group(1).strip()
        names_list = [n.strip() for n in names.split(",") if n.strip()]
        names_list.append("run_preview_for_employee_as_of")
        new_block = (
            "from app.services.payroll_runner import (\n"
            + "".join(f"    {n},\n" for n in names_list)
            + ")\n"
        )
        s = s[:m2.start()] + new_block + s[m2.end():]
        print(f"import: converted single-line ({names}) to multi-line + added fn")

# ---- Fix 2: as_of default ----
old = "    as_of: date | None = Query(None),\n"
if old in s:
    s = s.replace(old, "    as_of: date | None = None,\n", 1)
    print("signature: `as_of ... Query(None)` -> `as_of ... None`")
else:
    m3 = re.search(
        r"^(\s*)as_of\s*:\s*date\s*\|\s*None\s*=\s*Query\(None\),\s*$",
        s, re.M,
    )
    if m3:
        s = (
            s[:m3.start()] + m3.group(1) + "as_of: date | None = None,"
            + s[m3.end():]
        )
        print("signature: `as_of ... Query(None)` -> `... None` (regex)")
    elif "    as_of: date | None = None,\n" in s:
        print("signature: already `as_of: date | None = None`")
    else:
        print("WARN: could not locate as_of parameter")

P.write_text(s, encoding="utf-8")

# ---- Verify ----
s2 = P.read_text(encoding="utf-8")
print("\n=== VERIFY ===")
print("import above helper?",
      bool(re.search(r"\brun_preview_for_employee_as_of\b",
                    s2.split("def _preview_as_of", 1)[0])))
print("as_of default is None?",
      "    as_of: date | None = None,\n" in s2)
print("still Query(None)?",
      "    as_of: date | None = Query(None),\n" in s2)