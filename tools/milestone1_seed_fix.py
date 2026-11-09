"""Fix import: PayrollSettings lives in payroll_settings module, not pay."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "tools" / "milestone1_seed.py"
s = P.read_text(encoding="utf-8")

old = '''from app.db.tenant.models.pay import (
    PayPeriod,
    PayrollSettings,
    Payslip,
)
'''
new = '''from app.db.tenant.models.pay import (
    PayPeriod,
    Payslip,
)
from app.db.tenant.models.payroll_settings import PayrollSettings
'''
if old not in s:
    raise SystemExit("FATAL: pay import block not matched")
s = s.replace(old, new, 1)
P.write_text(s, encoding="utf-8")
print("patched: PayrollSettings now imported from payroll_settings module")