"""Locate the GET /preview/{employee_id} handler + print its full body."""
import re
from pathlib import Path

api_dir = Path("app/api/v1")
hits = []
for py in api_dir.rglob("*.py"):
    try:
        text = py.read_text(encoding="utf-8")
    except Exception:
        continue
    if '"/preview/{employee_id}"' in text or "'/preview/{employee_id}'" in text:
        hits.append(py)
    elif "preview/{employee_id}" in text and "/preview/" in text:
        # fallback string-based match
        if "employee_id" in text and "preview" in text.lower() and "@router" in text:
            hits.append(py)

# de-dupe
seen = set()
for py in hits:
    rp = str(py)
    if rp in seen:
        continue
    seen.add(rp)
    print(f"=== FILE: {py} ===")
    text = py.read_text(encoding="utf-8")
    lines = text.split("\n")
    # print every block that mentions preview/employee_id
    for i, line in enumerate(lines):
        if 'preview/{employee_id}' in line or ("preview" in line.lower() and "employee_id" in line and "@router" in line):
            start = max(0, i - 2)
            end = min(len(lines), i + 60)
            for j in range(start, end):
                print(f"{j+1:4}: {lines[j]}")
            print("---")
            break

if not seen:
    print("No handler found. Listing all files that mention preview:")
    for py in api_dir.rglob("*.py"):
        try:
            t = py.read_text(encoding="utf-8")
        except Exception:
            continue
        if "preview" in t.lower() and "employee" in t.lower():
            print(f"  {py}")

print("\n=== payroll_preview.py exists? ===")
for name in ("payroll_preview.py", "payroll_payslips.py", "payroll_pay_periods.py"):
    p = api_dir / name
    if p.exists():
        text = p.read_text(encoding="utf-8")
        matches = []
        for i, line in enumerate(text.split("\n"), 1):
            if "employee_id" in line and "preview" in line.lower():
                matches.append((i, line.strip()))
        if matches:
            print(f"  {name}: {len(matches)} matches (first 5):")
            for ln, l in matches[:5]:
                print(f"    L{ln}: {l}")