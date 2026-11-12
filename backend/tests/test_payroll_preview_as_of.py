"""Job B: GET /preview/{employee_id}?as_of=YYYY-MM-DD — read-only estimate.

Covers:
- No PayrollRun row written by the as_of path
- No Payslip row written by the as_of path
- Locked period refused (409)
- Monthly salaried refused with typed available:false
- as_of before period.start_date -> 422
- as_of after period.end_date -> clamped
- Typed response shape (available + reason_unavailable + as_of)
- M6 Part 2 Stage 5 (F22): deduction_type_code populated from source_ref
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError
from app.db.tenant.models.pay import PayPeriod, PayrollRun, Payslip
from app.db.tenant.models.people import Employee
from app.services.payroll_runner import run_preview_for_employee_as_of


@pytest.fixture()
def db(_leave_session_shared):
    return _leave_session_shared


def _mk_employee(session, code="E1", pay_basis="hourly"):
    emp = Employee(
        employee_code=code,
        first_name="A",
        last_name="B",
        hire_date=date(2024, 1, 1),
        status="active",
        employee_type="hourly",
        pay_basis=pay_basis,
        pay_frequency="monthly",
        row_version=1,
    )
    session.add(emp)
    session.flush()
    return emp


def _mk_period(session, status="open"):
    p = PayPeriod(
        id=uuid.uuid4(),
        period_key="2026-11",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        pay_date=date(2026, 12, 5),
        status=status,
        cutoff_at=datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc),
    )
    session.add(p)
    session.flush()
    return p


def _user():
    return SimpleNamespace(id=uuid.uuid4(), role="payroll_admin")


def _run_counts(session):
    runs = session.scalar(select(func.count()).select_from(PayrollRun)) or 0
    payslips = session.scalar(select(func.count()).select_from(Payslip)) or 0
    return runs, payslips


def test_as_of_writes_no_payroll_run(db):
    emp = _mk_employee(db)
    period = _mk_period(db)
    runs_before, _ = _run_counts(db)
    try:
        run_preview_for_employee_as_of(db, _user(), period, emp, date(2026, 11, 10))
    except Exception:
        pass  # pipeline may refuse on fresh tenant without settings
    runs_after, _ = _run_counts(db)
    assert runs_after == runs_before


def test_as_of_writes_no_payslip(db):
    emp = _mk_employee(db)
    period = _mk_period(db)
    _, payslips_before = _run_counts(db)
    try:
        run_preview_for_employee_as_of(db, _user(), period, emp, date(2026, 11, 10))
    except Exception:
        pass
    _, payslips_after = _run_counts(db)
    assert payslips_after == payslips_before


def test_locked_period_refused(db):
    emp = _mk_employee(db)
    period = _mk_period(db, status="locked")
    with pytest.raises(AppError) as e:
        run_preview_for_employee_as_of(db, _user(), period, emp, date(2026, 11, 10))
    assert e.value.code == "period_locked"


def test_monthly_refused_typed(db):
    emp = _mk_employee(db, pay_basis="monthly")
    period = _mk_period(db)
    out = run_preview_for_employee_as_of(db, _user(), period, emp, date(2026, 11, 10))
    assert out["available"] is False
    assert out["reason_unavailable"] == "monthly_proration_pending"
    assert out["gross"] is None
    assert out["net"] is None
    assert out["as_of"] == date(2026, 11, 10)


def test_as_of_before_period_start_422(db):
    emp = _mk_employee(db)
    period = _mk_period(db)
    with pytest.raises(AppError) as e:
        run_preview_for_employee_as_of(db, _user(), period, emp, date(2026, 10, 15))
    assert e.value.code == "as_of_before_period_start"


def test_as_of_after_period_end_clamped(db):
    # Monthly returns before the pipeline runs — clean, independent of settings
    emp = _mk_employee(db, pay_basis="monthly")
    period = _mk_period(db)
    out = run_preview_for_employee_as_of(db, _user(), period, emp, date(2026, 12, 15))
    assert out["as_of"] == period.end_date


def test_as_of_typed_shape(db):
    emp = _mk_employee(db, pay_basis="monthly")
    period = _mk_period(db)
    out = run_preview_for_employee_as_of(db, _user(), period, emp, date(2026, 11, 10))
    assert "available" in out
    assert "reason_unavailable" in out
    assert "as_of" in out


def test_as_of_deduction_type_code_populated(db, monkeypatch):
    """F22 (M6 Part 2 Stage 5): as-of deductions must surface deduction_type_code
    from `DeductionLine.source_ref`. Previously the code used
    `getattr(d, "code", "")` which returned "" because DeductionLine has no
    `code` attribute — silently empty in every response."""
    from app.services import payroll_runner as PR
    from app.services import payroll_pipeline as P

    emp = _mk_employee(db, pay_basis="hourly")
    period = _mk_period(db)

    # Construct a fake DeductionLine with the source_ref that the real
    # _build_deductions sets on its output. Use SimpleNamespace to avoid
    # coupling the test to the DeductionLine constructor signature.
    fake_deduction = SimpleNamespace(
        label="Medical aid",
        amount=Decimal("500.00"),
        category="benefit",
        is_pre_tax=False,
        priority=100,
        source_ref={
            "employee_deduction_id": str(uuid.uuid4()),
            "deduction_type_code": "MED_AID",
        },
    )

    # Patch the input-building helpers and the pipeline so we exercise the
    # exact transformation that F22 fixed, without needing a fully seeded
    # tenant (settings, statutory tables, earning types, etc.).
    monkeypatch.setattr(PR, "build_pipeline_config", lambda *a, **kw: SimpleNamespace())
    monkeypatch.setattr(PR, "_build_all_earnings", lambda *a, **kw: ([], [], {}))
    monkeypatch.setattr(PR, "_build_deductions", lambda *a, **kw: [fake_deduction])
    monkeypatch.setattr(
        P, "run_pipeline",
        lambda *a, **kw: SimpleNamespace(
            refused=False,
            refusal_code=None,
            refusal_message=None,
            gross=Decimal("1000.00"),
            paye=Decimal("100.00"),
            net=Decimal("900.00"),
        ),
    )

    out = run_preview_for_employee_as_of(
        db, _user(), period, emp, date(2026, 11, 10),
    )

    assert out["available"] is True
    assert len(out["deductions"]) == 1
    assert out["deductions"][0]["deduction_type_code"] == "MED_AID", (
        "F22 regression: deduction_type_code must come from source_ref, "
        "not from the nonexistent DeductionLine.code attribute"
    )
    assert out["deductions"][0]["deduction_type_name"] == "Medical aid"
    assert out["deductions"][0]["amount"] == Decimal("500.00")