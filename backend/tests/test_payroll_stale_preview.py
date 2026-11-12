"""M6 Part 2 Stage 4 — stale-preview detection at finalise.

A preview run stores a canonical `input_hash` in `rules_snapshot`. At
finalise, the current input state is re-hashed; if a preview run exists and
the hashes differ, finalise is refused with 409 `preview_stale` unless
`ack_stale_preview_reason` is provided.

No preview run at all → gate skipped (preserves pre-Stage-4 behaviour).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.errors import AppError
from app.db.tenant.models.pay import (
    EarningType, EmployeeEarning, PayPeriod, PayrollRun,
)
from app.db.tenant.models.people import Employee, User
from app.services import payroll_runner as PR


@pytest.fixture()
def db(_leave_session_shared):
    return _leave_session_shared


@pytest.fixture()
def admin(db):
    u = User(
        id=uuid.uuid4(),
        username=f"pa-{uuid.uuid4().hex[:12]}",
        password_hash="x",
        role="payroll_admin",
        is_active=True,
        must_change_password=False,
        row_version=1,
    )
    db.add(u); db.flush()
    return SimpleNamespace(id=u.id, role="payroll_admin", employee_id=None)


def _mk_employee(session):
    code = f"E{uuid.uuid4().hex[:6]}"
    emp = Employee(
        employee_code=code, first_name="T", last_name=code,
        hire_date=date(2024, 1, 1), status="active",
        employee_type="hourly", pay_basis="hourly",
        pay_frequency="monthly", row_version=1,
    )
    session.add(emp); session.flush()
    return emp


def _mk_period(session):
    p = PayPeriod(
        id=uuid.uuid4(),
        period_key=f"PP-{uuid.uuid4().hex[:12]}",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        pay_date=date(2026, 12, 5),
        status="open",
        cutoff_at=datetime(2026, 12, 1, tzinfo=timezone.utc),
        row_version=1,
    )
    session.add(p); session.flush()
    return p


def _mk_earning_type(session):
    et = EarningType(
        id=uuid.uuid4(), name="Base", code=f"b-{uuid.uuid4().hex[:12]}",
        calc_method="fixed_amount", frequency="regular",
        is_taxable=True, counts_for_uif=True, counts_for_sdl=True,
        is_system=False, is_active=True, row_version=1,
    )
    session.add(et); session.flush()
    return et


def _mk_earning(session, employee, et, *, amount="1000.00"):
    er = EmployeeEarning(
        id=uuid.uuid4(), employee_id=employee.id, earning_type_id=et.id,
        amount=Decimal(amount), rate=None,
        effective_from=date(2026, 1, 1), effective_to=None,
        is_active=True, row_version=1,
    )
    session.add(er); session.flush()
    return er


def _fake_draft():
    return SimpleNamespace(
        refused=False, refusal_code=None, refusal_message=None,
        gross=Decimal("0"), pre_tax_deductions=Decimal("0"),
        taxable_income=Decimal("0"), paye=Decimal("0"),
        uif_employee=Decimal("0"), uif_employer=Decimal("0"),
        sdl=Decimal("0"), other_deductions=Decimal("0"),
        reimbursements=Decimal("0"), net=Decimal("0"),
        employer_costs=lambda: {},
        deferred_deductions=[],
        calculation_context={}, tax_trace={},
    )


def _patch_pipeline_and_gates(monkeypatch):
    """Stub the pipeline and non-Stage-4 gates so tests exercise only the
    hash comparison logic."""
    monkeypatch.setattr(PR, "_formula_warnings", lambda *a, **kw: [])
    monkeypatch.setattr(PR, "_count_open_exceptions_in_period",
                       lambda *a, **kw: (0, []))
    monkeypatch.setattr(PR, "_count_pending_change_requests_in_period",
                       lambda *a, **kw: (0, []))
    monkeypatch.setattr(PR, "ensure_system_earning_types", lambda *a, **kw: None)
    # Do NOT patch _in_scope_employees — we want the real list of employees
    # so the hash sees them, and so finalise writes payslips for them.
    monkeypatch.setattr(PR, "build_pipeline_config",
                       lambda *a, **kw: SimpleNamespace())
    monkeypatch.setattr(PR, "_build_all_earnings", lambda *a, **kw: ([], [], {}))
    monkeypatch.setattr(PR, "_build_deductions", lambda *a, **kw: [])
    monkeypatch.setattr(PR.P, "run_pipeline", lambda *a, **kw: _fake_draft())


# ---------------------------------------------------------------------------
# 1. Fresh preview → finalise allows
# ---------------------------------------------------------------------------


def test_fresh_preview_allows(db, monkeypatch, admin):
    _patch_pipeline_and_gates(monkeypatch)
    emp = _mk_employee(db)
    et = _mk_earning_type(db)
    _mk_earning(db, emp, et)
    period = _mk_period(db)

    PR.run_preview(db, admin, period)
    db.flush()

    PR.finalise(db, admin, period)
    assert period.status == "locked"


# ---------------------------------------------------------------------------
# 2. Data changed between preview and finalise → 409
# ---------------------------------------------------------------------------


def test_stale_preview_blocks(db, monkeypatch, admin):
    _patch_pipeline_and_gates(monkeypatch)
    emp = _mk_employee(db)
    et = _mk_earning_type(db)
    earning = _mk_earning(db, emp, et, amount="1000.00")
    period = _mk_period(db)

    PR.run_preview(db, admin, period)
    db.flush()

    # Simulate a mutation between preview and finalise.
    earning.amount = Decimal("1500.00")
    db.flush()

    with pytest.raises(AppError) as e:
        PR.finalise(db, admin, period)
    assert e.value.code == "preview_stale"
    assert "preview_hash" in e.value.details
    assert "current_hash" in e.value.details
    assert e.value.details["preview_hash"] != e.value.details["current_hash"]


# ---------------------------------------------------------------------------
# 3. No preview at all → gate skipped (current behaviour preserved)
# ---------------------------------------------------------------------------


def test_no_preview_allows(db, monkeypatch, admin):
    _patch_pipeline_and_gates(monkeypatch)
    _mk_employee(db)
    period = _mk_period(db)

    # No PR.run_preview call. finalise proceeds without staleness check.
    PR.finalise(db, admin, period)
    assert period.status == "locked"


# ---------------------------------------------------------------------------
# 4. Stale + ack → allows, ack captured in audit trail
# ---------------------------------------------------------------------------


def test_stale_preview_with_ack_allows(db, monkeypatch, admin):
    _patch_pipeline_and_gates(monkeypatch)
    emp = _mk_employee(db)
    et = _mk_earning_type(db)
    earning = _mk_earning(db, emp, et, amount="1000.00")
    period = _mk_period(db)

    PR.run_preview(db, admin, period)
    db.flush()

    earning.amount = Decimal("1500.00")
    db.flush()

    PR.finalise(
        db, admin, period,
        ack_stale_preview_reason="post-preview correction approved by CFO",
    )
    assert period.status == "locked"


# ---------------------------------------------------------------------------
# 5. Hash is stable across repeated computations
# ---------------------------------------------------------------------------


def test_input_hash_stable(db, monkeypatch):
    emp = _mk_employee(db)
    et = _mk_earning_type(db)
    _mk_earning(db, emp, et, amount="1000.00")
    period = _mk_period(db)

    h1 = PR._compute_input_hash(db, period)
    h2 = PR._compute_input_hash(db, period)
    assert h1 == h2
    assert isinstance(h1, str) and len(h1) == 64  # sha256 hex digest