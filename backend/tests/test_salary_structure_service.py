"""Milestone 3 Stage B — salary structure service tests.

Uses the pre-existing _leave_session_shared fixture (Session bound to a
transactional connection; rolled back at teardown). No db.commit() is
called from tests; service functions themselves do not commit. Router
commits — that contract is exercised later in Stage F integration.

Users for write_audit: the _leave_tenant_seeded fixture seeds an "admin"
User at session start; _mk_user(db) returns that real row so
audit_log.actor_user_id satisfies audit_log_actor_user_id_fkey.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.db.tenant.models.pay import DeductionType, EarningType
from app.db.tenant.models.people import User
from app.db.tenant.models.salary_structure import (
    SalaryStructure,
    SalaryStructureComponent,
)
from app.services.salary_structure_service import (
    create_structure,
    deactivate_group,
    edit_structure,
    get_current_structure,
    get_version,
    list_current_structures,
    list_versions,
)


# ----------------------------- helpers -----------------------------

def _mk_user(db):
    """Return the real 'admin' User seeded by _leave_tenant_seeded.

    Needed because write_audit writes audit_log.actor_user_id, which has
    an FK to user.id.
    """
    return db.query(User).filter(User.username == "admin").one()


def _mk_earning_type(db, *, code=None, is_system=False, is_active=True):
    code = code or f"ET{uuid.uuid4().hex[:8]}"
    et = EarningType(
        name="Earn",
        code=code,
        calc_method="fixed_amount",
        frequency="regular",
        is_taxable=True,
        counts_for_uif=True,
        counts_for_sdl=True,
        proration_rule="none",
        is_system=is_system,
        is_active=is_active,
        row_version=1,
    )
    db.add(et)
    db.flush()
    return et.id


def _mk_deduction_type(db, *, code=None, is_system=False, is_active=True):
    code = code or f"DT{uuid.uuid4().hex[:8]}"
    dt = DeductionType(
        name="Ded",
        code=code,
        category="other",
        priority=100,
        is_pre_tax=False,
        is_system=is_system,
        is_active=is_active,
        row_version=1,
    )
    db.add(dt)
    db.flush()
    return dt.id


def _mk_structure(db, *, name="S", base_rate="10000", components=None):
    return create_structure(
        db, _mk_user(db),
        name=name,
        description=None,
        pay_basis="monthly",
        base_rate=Decimal(base_rate),
        components=components or [],
    )


# ----------------------------- tests -----------------------------

def test_create_structure_basic(_leave_session_shared):
    db = _leave_session_shared
    s = _mk_structure(db)
    assert s.version_number == 1
    assert s.is_current is True
    assert s.is_active is True
    assert s.structure_group_id is not None


def test_create_structure_with_earning_component(_leave_session_shared):
    db = _leave_session_shared
    et = _mk_earning_type(db)
    s = _mk_structure(db, components=[{
        "kind": "earning",
        "earning_type_id": et,
        "deduction_type_id": None,
        "amount": Decimal("500.00"),
        "rate": None,
    }])
    comps = db.scalars(select(SalaryStructureComponent).where(
        SalaryStructureComponent.structure_id == s.id,
    )).all()
    assert len(comps) == 1
    assert comps[0].earning_type_id == et
    assert comps[0].amount == Decimal("500.00")


def test_create_structure_with_deduction_component(_leave_session_shared):
    db = _leave_session_shared
    dt = _mk_deduction_type(db)
    s = _mk_structure(db, components=[{
        "kind": "deduction",
        "earning_type_id": None,
        "deduction_type_id": dt,
        "amount": Decimal("200.00"),
        "rate": None,
    }])
    comps = db.scalars(select(SalaryStructureComponent).where(
        SalaryStructureComponent.structure_id == s.id,
    )).all()
    assert len(comps) == 1
    assert comps[0].deduction_type_id == dt


def test_create_structure_rejects_system_earning_type(_leave_session_shared):
    db = _leave_session_shared
    et = _mk_earning_type(db, is_system=True)
    with pytest.raises(AppError) as exc:
        _mk_structure(db, components=[{
            "kind": "earning",
            "earning_type_id": et,
            "deduction_type_id": None,
            "amount": Decimal("100"),
            "rate": None,
        }])
    assert exc.value.code == "system_earning_type_not_allowed_in_structure"


def test_create_structure_rejects_base_monthly(_leave_session_shared):
    db = _leave_session_shared
    et = _mk_earning_type(db, code="BASE_MONTHLY")
    with pytest.raises(AppError) as exc:
        _mk_structure(db, components=[{
            "kind": "earning",
            "earning_type_id": et,
            "deduction_type_id": None,
            "amount": Decimal("100"),
            "rate": None,
        }])
    assert exc.value.code == "base_monthly_component_not_allowed"


def test_create_structure_rejects_inactive_earning_type(_leave_session_shared):
    db = _leave_session_shared
    et = _mk_earning_type(db, is_active=False)
    with pytest.raises(AppError) as exc:
        _mk_structure(db, components=[{
            "kind": "earning",
            "earning_type_id": et,
            "deduction_type_id": None,
            "amount": Decimal("100"),
            "rate": None,
        }])
    assert exc.value.code == "inactive_earning_type_not_allowed"


def test_create_structure_rejects_system_deduction_type(_leave_session_shared):
    db = _leave_session_shared
    dt = _mk_deduction_type(db, is_system=True)
    with pytest.raises(AppError) as exc:
        _mk_structure(db, components=[{
            "kind": "deduction",
            "earning_type_id": None,
            "deduction_type_id": dt,
            "amount": Decimal("100"),
            "rate": None,
        }])
    assert exc.value.code == "system_deduction_not_allowed_in_structure"


def test_create_structure_rejects_inactive_deduction_type(_leave_session_shared):
    db = _leave_session_shared
    dt = _mk_deduction_type(db, is_active=False)
    with pytest.raises(AppError) as exc:
        _mk_structure(db, components=[{
            "kind": "deduction",
            "earning_type_id": None,
            "deduction_type_id": dt,
            "amount": Decimal("100"),
            "rate": None,
        }])
    assert exc.value.code == "inactive_deduction_type_not_allowed"


def test_edit_creates_new_version_and_preserves_old(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    et = _mk_earning_type(db)
    s1 = create_structure(
        db, user,
        name="S", description=None, pay_basis="monthly",
        base_rate=Decimal("10000"),
        components=[{
            "kind": "earning", "earning_type_id": et,
            "deduction_type_id": None,
            "amount": Decimal("500"), "rate": None,
        }],
    )
    s1_id = s1.id
    group_id = s1.structure_group_id
    s2 = edit_structure(
        db, user, group_id,
        version_number=1, row_version=1,
        base_rate=Decimal("12000"),
    )
    assert s2.version_number == 2
    assert s2.is_current is True
    assert s2.base_rate == Decimal("12000")
    old = db.get(SalaryStructure, s1_id)
    assert old.is_current is False
    assert old.version_number == 1
    assert old.base_rate == Decimal("10000")
    old_comps = db.scalars(select(SalaryStructureComponent).where(
        SalaryStructureComponent.structure_id == s1_id,
    )).all()
    new_comps = db.scalars(select(SalaryStructureComponent).where(
        SalaryStructureComponent.structure_id == s2.id,
    )).all()
    assert len(old_comps) == 1
    assert len(new_comps) == 1
    assert old_comps[0].amount == Decimal("500")
    assert new_comps[0].amount == Decimal("500")
    assert old_comps[0].id != new_comps[0].id


def test_edit_rejects_stale_version_number(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    s1 = _mk_structure(db)
    group_id = s1.structure_group_id
    edit_structure(
        db, user, group_id,
        version_number=1, row_version=1, base_rate=Decimal("12000"),
    )
    with pytest.raises(AppError) as exc:
        edit_structure(
            db, user, group_id,
            version_number=1, row_version=1, base_rate=Decimal("14000"),
        )
    assert exc.value.code == "record_changed"


def test_edit_rejects_row_version_mismatch(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    s = _mk_structure(db)
    with pytest.raises(AppError) as exc:
        edit_structure(
            db, user, s.structure_group_id,
            version_number=1, row_version=99, base_rate=Decimal("12000"),
        )
    assert exc.value.code == "record_changed"


def test_edit_rejects_inactive_group(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    s = _mk_structure(db)
    group_id = s.structure_group_id
    deactivate_group(db, user, group_id)
    with pytest.raises(AppError) as exc:
        edit_structure(
            db, user, group_id,
            version_number=1, row_version=1, base_rate=Decimal("12000"),
        )
    assert exc.value.code == "structure_inactive"


def test_deactivate_group_sets_all_versions_inactive(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    s1 = _mk_structure(db)
    group_id = s1.structure_group_id
    edit_structure(
        db, user, group_id,
        version_number=1, row_version=1, base_rate=Decimal("12000"),
    )
    deactivate_group(db, user, group_id)
    rows = db.scalars(select(SalaryStructure).where(
        SalaryStructure.structure_group_id == group_id,
    )).all()
    assert len(rows) == 2
    for r in rows:
        assert r.is_active is False


def test_list_versions_returns_all(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    s1 = _mk_structure(db)
    group_id = s1.structure_group_id
    edit_structure(
        db, user, group_id,
        version_number=1, row_version=1, base_rate=Decimal("12000"),
    )
    versions = list_versions(db, group_id)
    assert [v.version_number for v in versions] == [1, 2]
    assert versions[1].is_current is True
    assert versions[0].is_current is False


def test_get_current_structure_not_found(_leave_session_shared):
    db = _leave_session_shared
    with pytest.raises(AppError) as exc:
        get_current_structure(db, uuid.uuid4())
    assert exc.value.code == "not_found"


def test_get_version_specific(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    s1 = _mk_structure(db)
    group_id = s1.structure_group_id
    edit_structure(
        db, user, group_id,
        version_number=1, row_version=1, base_rate=Decimal("12000"),
    )
    v1 = get_version(db, group_id, 1)
    v2 = get_version(db, group_id, 2)
    assert v1.base_rate == Decimal("10000")
    assert v2.base_rate == Decimal("12000")
    assert v1.is_current is False
    assert v2.is_current is True


def test_list_current_structures(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    s1 = _mk_structure(db, name="Alpha")
    _mk_structure(db, name="Beta")
    edit_structure(
        db, user, s1.structure_group_id,
        version_number=1, row_version=1, base_rate=Decimal("12000"),
    )
    currents = list_current_structures(db)
    names = sorted(s.name for s in currents)
    assert "Alpha" in names
    assert "Beta" in names
    for s in currents:
        assert s.is_current is True

# END OF FILE