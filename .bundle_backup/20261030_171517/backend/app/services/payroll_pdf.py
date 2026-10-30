"""Minimal PDF renderer for payslips (Chapter 4, Bundle 004b-b).

No external dependency (no reportlab). Renders a single-page text PDF
containing the standard payslip fields, which is sufficient for a proof-of-
concept and a mechanical correctness check. Upgrading to a nicer layout is
a follow-up that swaps this module only.

Storage via StorageDep is deferred (documented in STATE.md at 016c). The
endpoint returns bytes on demand.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    return str(v)


def _payslip_text_lines(payslip: Any, employee: Any, pay_period: Any) -> list[str]:
    code = getattr(employee, "employee_code", "") or ""
    name = " ".join(
        x for x in (getattr(employee, "first_name", "") or "", getattr(employee, "last_name", "") or "")
        if x
    ).strip()
    period = getattr(pay_period, "period_key", "") or ""
    pay_date = getattr(pay_period, "pay_date", "")
    revision = getattr(payslip, "revision", 1)
    status = getattr(payslip, "status", "")

    lines = [
        f"PAYSLIP  {period}  ({pay_date})",
        f"Employee: {code}  {name}".rstrip(),
        f"Revision: {revision}  Status: {status}",
        "",
        f"Gross                 {_fmt(getattr(payslip, 'gross', None))}",
        f"Pre-tax deductions    {_fmt(getattr(payslip, 'pre_tax_deductions', None))}",
        f"Taxable income        {_fmt(getattr(payslip, 'taxable_income', None))}",
        f"PAYE                  {_fmt(getattr(payslip, 'paye', None))}",
        f"UIF (employee)        {_fmt(getattr(payslip, 'uif_employee', None))}",
        f"Other deductions      {_fmt(getattr(payslip, 'other_deductions', None))}",
        f"Reimbursements        {_fmt(getattr(payslip, 'reimbursements', None))}",
        f"NET PAY               {_fmt(getattr(payslip, 'net', None))}",
        "",
        "Employer costs",
        f"UIF (employer)        {_fmt(getattr(payslip, 'uif_employer', None))}",
        f"SDL                   {_fmt(getattr(payslip, 'sdl', None))}",
    ]
    return lines


def _render_minimal_pdf(lines: list[str]) -> bytes:
    """Construct a valid single-page PDF (Courier, 10pt) from text lines."""
    content = ["BT", "/F1 10 Tf", "14 TL", "50 780 Td"]
    for i, line in enumerate(lines):
        if i > 0:
            content.append("T*")
        content.append(f"({_esc(line)}) Tj")
    content.append("ET")
    stream = "\n".join(content).encode("latin-1", errors="replace")

    objs: list[bytes] = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objs.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
    )
    objs.append(
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    )
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")

    out = bytearray()
    out += b"%PDF-1.4\n"
    offsets = [0]
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode()
        out += o
        out += b"\nendobj\n"
    xref_offset = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += b"trailer\n"
    out += f"<< /Size {len(objs) + 1} /Root 1 0 R >>\n".encode()
    out += b"startxref\n"
    out += f"{xref_offset}\n".encode()
    out += b"%%EOF\n"
    return bytes(out)


def render_payslip_pdf(payslip: Any, employee: Any, pay_period: Any) -> bytes:
    return _render_minimal_pdf(_payslip_text_lines(payslip, employee, pay_period))

# END OF FILE
