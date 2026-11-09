"""Stage C — submit-time guards for salary assignment."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.core.errors import AppError
from app.db.tenant.models.pay import (
    DeductionType, EarningType, EmployeeDeduction, EmployeeEarning, PayPeriod,
)
from app.db.tenant.models.people import Employee, User
from app.db.tenant.models.salary_structure import (
    EmployeeSalaryStructureAssignment,
    SalaryStructure,
)
from app.services.salary_assignment_service import (
    check_collisions,
    submit_assignment,
)
from app.services.salary_structure_service import (
    create_structure,
)


# ----------------------------- helpers -----------------------------

def _mk_user(db):
    return db.query(User).filter(User.username == "admin").one()


def _mk_employee(db, *, pay_basis="monthly", code=None):
    code = code or f"E{uuid.uuid4().hex[:8]}"
    emp = Employee(
        employee_code=code,
        first_name="Test", last_name="Emp",
        hire_date=date.today() - timedelta(days=365),
        employee_type="monthly" if pay_basis == "monthly" else "hourly",
        pay_basis=pay_basis,
        pay_frequency="monthly",
        overtime_eligible=True, clocks=True, uif_exempt=False,
        medical_aid_dependants=0, medical_scheme_members=0,
        row_version=1,
    )
    db.add(emp)
    db.flush()
    return emp


def _mk_structure(db, *, user, pay_basis="monthly"):
    return create_structure(
        db, user,
        name=f"S{uuid.uuid4().hex[:6]}",
        description=None, pay_basis=pay_basis,
        base_rate=Decimal("15000"),
        components=[],
    )


def _mk_open_period(db, *, start, end, pay_date):
    p = PayPeriod(
        id=uuid.uuid4(),
        period_key=f"P{uuid.uuid4().hex[:6]}",
        start_date=start, end_date=end, pay_date=pay_date,
        status="open",
        cutoff_at=__import__("datetime").datetime.utcnow(),
    )
    db.add(p)
    db.flush()
    return p


def _mk_closed_period(db, *, start, end, pay_date):
    p = PayPeriod(
        id=uuid.uuid4(),
        period_key=f"P{uuid.uuid4().hex[:6]}",
        start_date=start, end_date=end, pay_date=pay_date,
        status="closed",
        cutoff_at=__import__("datetime").datetime.utcnow(),
    )
    db.add(p)
    db.flush()
    return p


def _mk_valid_date_env(db):
    """Create one closed period and one open period far in the future so
    a boundary date exists ahead of today that is not affected by any
    open period's pay_date."""
    today = date.today()
    # Closed period ending soon; its end_date+1 is a valid boundary.
    start = today + timedelta(days=10)
    end = start + timedelta(days=6)
    _mk_closed_period(db, start=start, end=end,
                       pay_date=end + timedelta(days=1))
    return end + timedelta(days=1)  # boundary and > today, > no open pay_date


# ----------------------------- tests -----------------------------

def test_submit_happy_path(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    structure = _mk_structure(db, user=user)
    d = _mk_valid_date_env(db)

    a = submit_assignment(
        db, user,
        employee_id=emp.id, structure_id=structure.id,
        effective_from=d, idempotency_key=None,
        override_manual_ids=[],
    )
    assert a.status == "pending"
    assert a.effective_from == d
    assert a.employee_id == emp.id
    assert a.structure_id == structure.id


def test_submit_rejects_backdating(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    structure = _mk_structure(db, user=user)
    _mk_valid_date_env(db)
    with pytest.raises(AppError) as exc:
        submit_assignment(
            db, user,
            employee_id=emp.id, structure_id=structure.id,
            effective_from=date.today(), idempotency_key=None,
            override_manual_ids=[],
        )
    assert exc.value.code == "backdating_not_permitted"


def test_submit_rejects_no_pay_periods(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    structure = _mk_structure(db, user=user)
    with pytest.raises(AppError) as exc:
        submit_assignment(
            db, user,
            employee_id=emp.id, structure_id=structure.id,
            effective_from=date.today() + timedelta(days=20),
            idempotency_key=None, override_manual_ids=[],
        )
    assert exc.value.code == "no_pay_periods_configured"


def test_submit_rejects_effective_date_affects_open_period(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    structure = _mk_structure(db, user=user)
    today = date.today()
    start = today + timedelta(days=10)
    end = start + timedelta(days=6)
    _mk_open_period(db, start=start, end=end,
                    pay_date=end + timedelta(days=1))
    # boundary is end+1, but that boundary is affected by the open
    # period whose pay_date == end+1 (>= boundary)
    with pytest.raises(AppError) as exc:
        submit_assignment(
            db, user,
            employee_id=emp.id, structure_id=structure.id,
            effective_from=end + timedelta(days=1),
            idempotency_key=None, override_manual_ids=[],
        )
    assert exc.value.code == "effective_date_affects_open_period"


def test_submit_rejects_non_boundary_date(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    structure = _mk_structure(db, user=user)
    today = date.today()
    start = today + timedelta(days=10)
    end = start + timedelta(days=6)
    _mk_closed_period(db, start=start, end=end,
                      pay_date=end + timedelta(days=1))
    with pytest.raises(AppError) as exc:
        submit_assignment(
            db, user,
            employee_id=emp.id, structure_id=structure.id,
            effective_from=start + timedelta(days=2),
            idempotency_key=None, override_manual_ids=[],
        )
    assert exc.value.code == "effective_date_not_period_boundary"


def test_submit_rejects_pay_basis_mismatch(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db, pay_basis="hourly")
    structure = _mk_structure(db, user=user, pay_basis="monthly")
    d = _mk_valid_date_env(db)
    with pytest.raises(AppError) as exc:
        submit_assignment(
            db, user,
            employee_id=emp.id, structure_id=structure.id,
            effective_from=d, idempotency_key=None,
            override_manual_ids=[],
        )
    assert exc.value.code == "pay_basis_mismatch"


def test_submit_rejects_inactive_structure(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    structure = _mk_structure(db, user=user)
    structure.is_active = False
    db.flush()
    d = _mk_valid_date_env(db)
    with pytest.raises(AppError) as exc:
        submit_assignment(
            db, user,
            employee_id=emp.id, structure_id=structure.id,
            effective_from=d, idempotency_key=None,
            override_manual_ids=[],
        )
    assert exc.value.code == "structure_inactive"


def test_submit_rejects_not_current_structure(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    structure = _mk_structure(db, user=user)
    structure.is_current = False
    db.flush()
    d = _mk_valid_date_env(db)
    with pytest.raises(AppError) as exc:
        submit_assignment(
            db, user,
            employee_id=emp.id, structure_id=structure.id,
            effective_from=d, idempotency_key=None,
            override_manual_ids=[],
        )
    assert exc.value.code == "structure_not_current"


def test_submit_rejects_pending_assignment_exists(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    structure = _mk_structure(db, user=user)
    d = _mk_valid_date_env(db)
    submit_assignment(
        db, user,
        employee_id=emp.id, structure_id=structure.id,
        effective_from=d, idempotency_key=None, override_manual_ids=[],
    )
    with pytest.raises(AppError) as exc:
        submit_assignment(
            db, user,
            employee_id=emp.id, structure_id=structure.id,
            effective_from=d, idempotency_key=None, override_manual_ids=[],
        )
    assert exc.value.code == "pending_salary_structure_assignment_exists"


def test_submit_rejects_blocking_individual_cr(_leave_session_shared):
    from app.db.tenant.models.change_request import PayrollChangeRequest
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    structure = _mk_structure(db, user=user)
    d = _mk_valid_date_env(db)
    db.add(PayrollChangeRequest(
        id=uuid.uuid4(), kind="employee_earning_create",
        employee_id=emp.id,
        payload={"earning_type_id": str(uuid.uuid4()), "amount": "100"},
        status="pending",
        requested_by_user_id=user.id,
    ))
    db.flush()
    with pytest.raises(AppError) as exc:
        submit_assignment(
            db, user,
            employee_id=emp.id, structure_id=structure.id,
            effective_from=d, idempotency_key=None, override_manual_ids=[],
        )
    assert exc.value.code == "pending_individual_change_requests_block_assignment"


def test_submit_rejects_invalid_override_id(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    structure = _mk_structure(db, user=user)
    d = _mk_valid_date_env(db)
    with pytest.raises(AppError) as exc:
        submit_assignment(
            db, user,
            employee_id=emp.id, structure_id=structure.id,
            effective_from=d, idempotency_key=None,
            override_manual_ids=[
                {"kind": "employee_earning", "id": uuid.uuid4()},
            ],
        )
    assert exc.value.code == "invalid_override_manual_id"
    assert exc.value.details.get("reason") == "not_found"


def test_submit_rejects_unselected_earlier_start_collision(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    # Create a structure that CONTAINS the earning type
    et = EarningType(
        name="Bonus", code=f"B{uuid.uuid4().hex[:6]}",
        calc_method="fixed_amount", frequency="regular",
        is_taxable=True, counts_for_uif=True, counts_for_sdl=True,
        proration_rule="none", is_system=False, is_active=True, row_version=1,
    )
    db.add(et); db.flush()
    structure = create_structure(
        db, user, name="S-coll", description=None, pay_basis="monthly",
        base_rate=Decimal("15000"),
        components=[{
            "kind": "earning", "earning_type_id": et.id,
            "deduction_type_id": None,
            "amount": Decimal("500"), "rate": None,
        }],
    )
    d = _mk_valid_date_env(db)
    # Manual row with earlier effective_from and same type
    me = EmployeeEarning(
        employee_id=emp.id, earning_type_id=et.id,
        amount=Decimal("500"), effective_from=d - timedelta(days=60),
        is_active=True, row_version=1,
    )
    db.add(me); db.flush()

    with pytest.raises(AppError) as exc:
        submit_assignment(
            db, user,
            employee_id=emp.id, structure_id=structure.id,
            effective_from=d, idempotency_key=None,
            override_manual_ids=[],
        )
    assert exc.value.code == "manual_component_type_collision"


def test_submit_accepts_selected_earlier_start_collision(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    et = EarningType(
        name="Bonus", code=f"B{uuid.uuid4().hex[:6]}",
        calc_method="fixed_amount", frequency="regular",
        is_taxable=True, counts_for_uif=True, counts_for_sdl=True,
        proration_rule="none", is_system=False, is_active=True, row_version=1,
    )
    db.add(et); db.flush()
    structure = create_structure(
        db, user, name="S-sel", description=None, pay_basis="monthly",
        base_rate=Decimal("15000"),
        components=[{
            "kind": "earning", "earning_type_id": et.id,
            "deduction_type_id": None,
            "amount": Decimal("500"), "rate": None,
        }],
    )
    d = _mk_valid_date_env(db)
    me = EmployeeEarning(
        employee_id=emp.id, earning_type_id=et.id,
        amount=Decimal("500"), effective_from=d - timedelta(days=60),
        is_active=True, row_version=1,
    )
    db.add(me); db.flush()

    a = submit_assignment(
        db, user,
        employee_id=emp.id, structure_id=structure.id,
        effective_from=d, idempotency_key=None,
        override_manual_ids=[
            {"kind": "employee_earning", "id": me.id},
        ],
    )
    assert a.status == "pending"
    assert len(a.override_manual_ids) == 1


def test_submit_rejects_same_start_manual_collision(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    et = EarningType(
        name="Bonus", code=f"B{uuid.uuid4().hex[:6]}",
        calc_method="fixed_amount", frequency="regular",
        is_taxable=True, counts_for_uif=True, counts_for_sdl=True,
        proration_rule="none", is_system=False, is_active=True, row_version=1,
    )
    db.add(et); db.flush()
    structure = create_structure(
        db, user, name="S-ss", description=None, pay_basis="monthly",
        base_rate=Decimal("15000"),
        components=[{
            "kind": "earning", "earning_type_id": et.id,
            "deduction_type_id": None,
            "amount": Decimal("500"), "rate": None,
        }],
    )
    d = _mk_valid_date_env(db)
    me = EmployeeEarning(
        employee_id=emp.id, earning_type_id=et.id,
        amount=Decimal("500"), effective_from=d,  # same start
        is_active=True, row_version=1,
    )
    db.add(me); db.flush()
    with pytest.raises(AppError) as exc:
        submit_assignment(
            db, user,
            employee_id=emp.id, structure_id=structure.id,
            effective_from=d, idempotency_key=None, override_manual_ids=[],
        )
    assert exc.value.code == "manual_component_same_start_date"


def test_submit_idempotency_returns_existing(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    structure = _mk_structure(db, user=user)
    d = _mk_valid_date_env(db)
    key = "idem-" + uuid.uuid4().hex
    a1 = submit_assignment(
        db, user,
        employee_id=emp.id, structure_id=structure.id,
        effective_from=d, idempotency_key=key, override_manual_ids=[],
    )
    a2 = submit_assignment(
        db, user,
        employee_id=emp.id, structure_id=structure.id,
        effective_from=d, idempotency_key=key, override_manual_ids=[],
    )
    assert a1.id == a2.id


def test_check_collisions_returns_candidates(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    emp = _mk_employee(db)
    et = EarningType(
        name="Bonus", code=f"B{uuid.uuid4().hex[:6]}",
        calc_method="fixed_amount", frequency="regular",
        is_taxable=True, counts_for_uif=True, counts_for_sdl=True,
        proration_rule="none", is_system=False, is_active=True, row_version=1,
    )
    db.add(et); db.flush()
    structure = create_structure(
        db, user, name="S-cc", description=None, pay_basis="monthly",
        base_rate=Decimal("15000"),
        components=[{
            "kind": "earning", "earning_type_id": et.id,
            "deduction_type_id": None,
            "amount": Decimal("500"), "rate": None,
        }],
    )
    d = _mk_valid_date_env(db)
    me = EmployeeEarning(
        employee_id=emp.id, earning_type_id=et.id,
        amount=Decimal("500"), effective_from=d - timedelta(days=60),
        is_active=True, row_version=1,
    )
    db.add(me); db.flush()
    result = check_collisions(
        db, user,
        employee_id=emp.id, structure_id=structure.id,
        effective_from=d, override_manual_ids=[],
    )
    assert any(m["kind"] == "employee_earning" and m["status"] == "requires_override"
               for m in result["manual"])

# END OF FILE