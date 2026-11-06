"""Best-effort friendly message for 'no_employee_record' in OwnPayslipsPage.
Only edits the visible error text; if the file shape differs, prints a warning
and leaves it alone."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "OwnPayslipsPage.tsx"
s = P.read_text(encoding="utf-8")

marker = "no_employee_record"
if marker in s:
    print("OwnPayslipsPage: no_employee_record already handled")
else:
    # Simplest safe change: replace the generic list-error string.
    # Look for common patterns used in this codebase.
    candidates = [
        (
            'strings.payslips.listError',
            'strings.payslips.listError + " (link your user to an employee record to see payslips)"',
        ),
        (
            '"Could not load your payslips."',
            '"You are not linked to an employee record — payslips are visible only to users linked to an employee."',
        ),
        (
            '"Could not load payslips."',
            '"You are not linked to an employee record — payslips are visible only to users linked to an employee."',
        ),
    ]
    changed = False
    for old, new in candidates:
        if old in s:
            s = s.replace(old, new, 1)
            P.write_text(s, encoding="utf-8")
            print(f"OwnPayslipsPage: replaced {old!r} with friendly message")
            changed = True
            break
    if not changed:
        print("OwnPayslipsPage: string not matched — file needs manual review")
        print("  Look for the 'Could not load' text and patch manually next turn")