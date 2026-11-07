"""Fix _mk_emp to use unique codes. Then we run one specific test to see its
real traceback in case it is not an employee-code collision."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "backend" / "tests" / "test_intelligence_decision_records.py"
s = P.read_text(encoding="utf-8")

old = '''def _mk_emp(session, code="T001") -> Employee:
    emp = Employee(
        id=uuid.uuid4(), employee_code=code,
'''
new = '''def _mk_emp(session, code: str | None = None) -> Employee:
    if code is None:
        code = f"E-{uuid.uuid4().hex[:8]}"
    emp = Employee(
        id=uuid.uuid4(), employee_code=code,
'''
if old not in s:
    raise SystemExit("FATAL: _mk_emp block not matched")
s = s.replace(old, new, 1)
P.write_text(s, encoding="utf-8")
print("patched _mk_emp to unique codes")