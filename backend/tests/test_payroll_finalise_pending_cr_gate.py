"""M6 Part 2 Stage 3 — finalise gate on pending change requests.

A pending CR blocks finalise iff approving it would change the payslips
produced by the period. The rule is effective-window overlap, with the
existing row's window also checked for update/deactivate kinds.
`employee_field_update` has no window and blocks by default. Malformed
payloads fail closed.

The gate is company-wide (not scoped to the caller), and there is no
acknowledgement path — admins must approve, reject, or cancel pending CRs
via the existing audited endpoints before retrying finalise.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.db.tenant.models.change_request import PayrollChangeRequest
from app.db.tenant.models.pay import (
    EarningType, EmployeeEarning, PayPeriod,
)
from app.db.tenant.models.people import Employee, User
from app.services import payroll_runner as PR


@pytest.fixture()
def db(_leave_session_shared):
    return _leave_session_shared


@pytest.fixture()
def admin(db):
    """A real payroll_admin User row so FK writes on started_by_user_id /
    actor_user_id / decided_by_user_id have a valid target.

    A SimpleNamespace with a random uuid would violate those FKs on flush —
    which is exactly why block tests passed (they raise before any FK write)
    and allow tests failed."""
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


def _mk_period(session, status="open"):
    p = PayPeriod(
        id=uuid.uuid4(),
        period_key=f"PP-{uuid.uuid4().hex[:12]}",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        pay_date=date(2026, 12, 5),
        status=status,
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


def _mk_earning(session, employee, et, *, effective_from, effective_to=None):
    er = EmployeeEarning(
        id=uuid.uuid4(), employee_id=employee.id, earning_type_id=et.id,
        amount=Decimal("1000.00"), rate=None,
        effective_from=effective_from, effective_to=effective_to,
        is_active=True, row_version=1,
    )
    session.add(er); session.flush()
    return er


def _mk_cr(session, *, kind, employee_id, payload, status="pending"):
    """Create a change request directly.

    requested_by_user_id is left as None — the column has an FK to user.id
    (nullable, ondelete="SET NULL"). Setting it to a random uuid would
    violate the FK on flush.
    """
    cr = PayrollChangeRequest(
        id=uuid.uuid4(),
        kind=kind,
        employee_id=employee_id,
        payload=payload,
        status=status,
        requested_by_user_id=None,
        row_version=1,
    )
    session.add(cr); session.flush()
    return cr


def _patch_unrelated_gates(monkeypatch):
    """Isolate the CR gate from formula / open-exceptions / pipeline /
    system-seed gates so tests exercise exactly one behaviour."""
    monkeypatch.setattr(PR, "_formula_warnings", lambda *a, **kw: [])
    monkeypatch.setattr(PR, "_count_open_exceptions_in_period",
                       lambda *a, **kw: (0, []))
    monkeypatch.setattr(PR, "_in_scope_employees", lambda *a, **kw: [])
    # ensure_system_earning_types requires PayrollSettings rows that the
    # shared test session doesn't seed. Not relevant to the CR gate; stub it.
    monkeypatch.setattr(PR, "ensure_system_earning_types", lambda *a, **kw: None)


# ---------------------------------------------------------------------------
# Block cases
# ---------------------------------------------------------------------------


def test_retroactive_ongoing_create_blocks(db, monkeypatch, admin):
    """A pending create with effective_from long before the period and no
    end date still affects the period (ongoing). Must block."""
    _patch_unrelated_gates(monkeypatch)
    emp = _mk_employee(db)
    period = _mk_period(db)
    _mk_cr(
        db, kind="employee_earning_create", employee_id=emp.id,
        payload={
            "earning_type_id": str(uuid.uuid4()),
            "amount": "500.00",
            "effective_from": "2026-01-01",
        },
    )
    with pytest.raises(AppError) as e:
        PR.finalise(db, admin, period)
    assert e.value.code == "pending_change_requests_in_period"
    assert e.value.details["count"] == 1


def test_boundary_start_blocks(db, monkeypatch, admin):
    """effective_from exactly == period.start_date must block (inclusive)."""
    _patch_unrelated_gates(monkeypatch)
    emp = _mk_employee(db)
    period = _mk_period(db)
    _mk_cr(
        db, kind="employee_earning_create", employee_id=emp.id,
        payload={
            "earning_type_id": str(uuid.uuid4()),
            "amount": "500.00",
            "effective_from": "2026-11-01",
            "effective_to": "2026-11-15",
        },
    )
    with pytest.raises(AppError) as e:
        PR.finalise(db, admin, period)
    assert e.value.code == "pending_change_requests_in_period"


def test_boundary_end_blocks(db, monkeypatch, admin):
    """effective_to exactly == period.end_date must block (inclusive)."""
    _patch_unrelated_gates(monkeypatch)
    emp = _mk_employee(db)
    period = _mk_period(db)
    _mk_cr(
        db, kind="employee_earning_create", employee_id=emp.id,
        payload={
            "earning_type_id": str(uuid.uuid4()),
            "amount": "500.00",
            "effective_from": "2026-11-15",
            "effective_to": "2026-11-30",
        },
    )
    with pytest.raises(AppError) as e:
        PR.finalise(db, admin, period)
    assert e.value.code == "pending_change_requests_in_period"


def test_update_existing_overlaps_blocks(db, monkeypatch, admin):
    """Existing window overlaps period; proposed shortens it to end BEFORE
    period. Approval would REMOVE the earning from period — must block."""
    _patch_unrelated_gates(monkeypatch)
    emp = _mk_employee(db)
    period = _mk_period(db)
    et = _mk_earning_type(db)
    earning = _mk_earning(
        db, emp, et, effective_from=date(2026, 1, 1), effective_to=None,
    )
    _mk_cr(
        db, kind="employee_earning_update", employee_id=emp.id,
        payload={
            "target_id": str(earning.id),
            "row_version": earning.row_version,
            "effective_to": "2026-10-31",
        },
    )
    with pytest.raises(AppError) as e:
        PR.finalise(db, admin, period)
    assert e.value.code == "pending_change_requests_in_period"


def test_update_existing_not_overlap_proposed_does_blocks(db, monkeypatch, admin):
    """Existing window ended before period; proposed extends into period.
    Approval would ADD the earning to period — must block."""
    _patch_unrelated_gates(monkeypatch)
    emp = _mk_employee(db)
    period = _mk_period(db)
    et = _mk_earning_type(db)
    earning = _mk_earning(
        db, emp, et,
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 10, 31),
    )
    _mk_cr(
        db, kind="employee_earning_update", employee_id=emp.id,
        payload={
            "target_id": str(earning.id),
            "row_version": earning.row_version,
            "effective_to": "2026-12-31",
        },
    )
    with pytest.raises(AppError) as e:
        PR.finalise(db, admin, period)
    assert e.value.code == "pending_change_requests_in_period"


def test_deactivate_existing_overlaps_blocks(db, monkeypatch, admin):
    _patch_unrelated_gates(monkeypatch)
    emp = _mk_employee(db)
    period = _mk_period(db)
    et = _mk_earning_type(db)
    earning = _mk_earning(
        db, emp, et, effective_from=date(2026, 1, 1), effective_to=None,
    )
    _mk_cr(
        db, kind="employee_earning_deactivate", employee_id=emp.id,
        payload={"target_id": str(earning.id), "row_version": earning.row_version},
    )
    with pytest.raises(AppError) as e:
        PR.finalise(db, admin, period)
    assert e.value.code == "pending_change_requests_in_period"


def test_employee_field_update_blocks(db, monkeypatch, admin):
    """No effective window; blocks by default."""
    _patch_unrelated_gates(monkeypatch)
    emp = _mk_employee(db)
    period = _mk_period(db)
    _mk_cr(
        db, kind="employee_field_update", employee_id=emp.id,
        payload={"row_version": emp.row_version, "uif_exempt": True},
    )
    with pytest.raises(AppError) as e:
        PR.finalise(db, admin, period)
    assert e.value.code == "pending_change_requests_in_period"


def test_malformed_payload_fail_safe_blocks(db, monkeypatch, admin):
    """Directly-inserted CR with malformed payload (no effective_from) must
    block via fail-safe, never silently pass."""
    _patch_unrelated_gates(monkeypatch)
    emp = _mk_employee(db)
    period = _mk_period(db)
    _mk_cr(
        db, kind="employee_earning_create", employee_id=emp.id,
        payload={},  # malformed
    )
    with pytest.raises(AppError) as e:
        PR.finalise(db, admin, period)
    assert e.value.code == "pending_change_requests_in_period"


# ---------------------------------------------------------------------------
# Allow cases
# ---------------------------------------------------------------------------


def test_future_dated_create_allows(db, monkeypatch, admin):
    _patch_unrelated_gates(monkeypatch)
    emp = _mk_employee(db)
    period = _mk_period(db)
    _mk_cr(
        db, kind="employee_earning_create", employee_id=emp.id,
        payload={
            "earning_type_id": str(uuid.uuid4()),
            "amount": "500.00",
            "effective_from": "2026-12-01",  # > period.end_date
        },
    )
    PR.finalise(db, admin, period)
    assert period.status == "locked"


def test_just_before_period_create_allows(db, monkeypatch, admin):
    _patch_unrelated_gates(monkeypatch)
    emp = _mk_employee(db)
    period = _mk_period(db)
    _mk_cr(
        db, kind="employee_earning_create", employee_id=emp.id,
        payload={
            "earning_type_id": str(uuid.uuid4()),
            "amount": "500.00",
            "effective_from": "2026-01-01",
            "effective_to": "2026-10-31",  # < period.start_date
        },
    )
    PR.finalise(db, admin, period)
    assert period.status == "locked"


def test_deactivate_existing_ended_before_allows(db, monkeypatch, admin):
    _patch_unrelated_gates(monkeypatch)
    emp = _mk_employee(db)
    period = _mk_period(db)
    et = _mk_earning_type(db)
    earning = _mk_earning(
        db, emp, et,
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 10, 31),
    )
    _mk_cr(
        db, kind="employee_earning_deactivate", employee_id=emp.id,
        payload={"target_id": str(earning.id), "row_version": earning.row_version},
    )
    PR.finalise(db, admin, period)
    assert period.status == "locked"


def test_no_pending_crs_allows(db, monkeypatch, admin):
    _patch_unrelated_gates(monkeypatch)
    period = _mk_period(db)
    PR.finalise(db, admin, period)
    assert period.status == "locked"