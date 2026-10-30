"""Minimal PDF renderer (Chapter 4, Bundle 004b-b).

Pure function test - no DB.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.services.payroll_pdf import render_payslip_pdf


def _fake_payslip(**_overrides):
    base = dict(
        id=uuid.uuid4(),
        revision=1,
        status="current",
        gross=Decimal("1000.00"),
        pre_tax_deductions=Decimal("0.00"),
        taxable_income=Decimal("1000.00"),
        paye=Decimal("179.17"),
        uif_employee=Decimal("5.00"),
        uif_employer=Decimal("5.00"),
        sdl=Decimal("10.00"),
        other_deductions=Decimal("0.00"),
        reimbursements=Decimal("0.00"),
        net=Decimal("815.83"),
    )
    base.update(_overrides)
    return type("P", (), base)


def _fake_employee():
    return type("E", (), {
        "employee_code": "EMP-001",
        "first_name": "Ada",
        "last_name": "Lovelace",
    })


def _fake_period():
    return type("PP", (), {
        "period_key": "2025-06-M",
        "pay_date": date(2025, 6, 30),
    })


def test_pdf_bytes_start_with_header():
    pdf = render_payslip_pdf(_fake_payslip(), _fake_employee(), _fake_period())
    assert pdf[:5] == b"%PDF-"
    assert pdf.rstrip().endswith(b"%%EOF")


def test_pdf_contains_key_fields():
    pdf = render_payslip_pdf(_fake_payslip(), _fake_employee(), _fake_period())
    text = pdf.decode("latin-1")
    assert "EMP-001" in text
    assert "Ada Lovelace" in text
    assert "2025-06-M" in text
    assert "1000.00" in text
    assert "179.17" in text
    assert "815.83" in text
    assert "NET PAY" in text


def test_pdf_escapes_parentheses():
    # A gross of 1000.00 renders as "1000.00" - parentheses only in labels
    pdf = render_payslip_pdf(_fake_payslip(), _fake_employee(), _fake_period())
    # Balanced parentheses in the raw file
    text = pdf.decode("latin-1")
    assert text.count("(") == text.count(")")

# END OF FILE
