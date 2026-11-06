"""Fix: use `= None` for as_of, not `Query(None)`, so direct-call tests
receive None (not the Query marker object).

FastAPI still treats `date | None = None` as a query parameter.
"""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "backend" / "app" / "api" / "v1" / "payroll_pay_periods.py"
s = P.read_text(encoding="utf-8")

old = "        as_of: date | None = Query(None),\n"
new = "        as_of: date | None = None,\n"
if old not in s:
    if new in s:
        print("already `= None` — no change")
    else:
        # fallback: find any as_of param line
        import re
        m = re.search(r"^(\s*)as_of\s*:[^\n]*$", s, re.M)
        if not m:
            raise SystemExit("FATAL: as_of parameter not found")
        s = s[:m.start()] + m.group(1) + "as_of: date | None = None," + s[m.end():]
        P.write_text(s, encoding="utf-8")
        print(f"replaced as_of default via regex: {m.group(0)!r} -> 'as_of: date | None = None,'")
else:
    s = s.replace(old, new, 1)
    P.write_text(s, encoding="utf-8")
    print("replaced `as_of: date | None = Query(None)` -> `as_of: date | None = None`")