"""Stage D — ensure_base_monthly_type bootstrap tests."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.db.tenant.models.pay import EarningType
from app.services.salary_assignment_approve_service import ensure_base_monthly_type


def test_ensure_base_monthly_creates_when_missing(_leave_session_shared):
    db = _leave_session_shared
    existing = db.scalar(select(EarningType).where(EarningType.code == "BASE_MONTHLY"))
    assert existing is None
    et = ensure_base_monthly_type(db)
    assert et.code == "BASE_MONTHLY"
    assert et.calc_method == "fixed_amount"
    assert et.frequency == "regular"
    assert et.is_taxable is True
    assert et.counts_for_uif is True
    assert et.counts_for_sdl is True
    assert et.proration_rule == "none"
    assert et.is_system is False  # per F11
    assert et.is_active is True


def test_ensure_base_monthly_returns_existing_matching(_leave_session_shared):
    db = _leave_session_shared
    et1 = ensure_base_monthly_type(db)
    et2 = ensure_base_monthly_type(db)
    assert et1.id == et2.id


def test_ensure_base_monthly_raises_on_critical_mismatch(_leave_session_shared):
    db = _leave_session_shared
    et = EarningType(
        code="BASE_MONTHLY", name="Old base",
        calc_method="fixed_amount",
        frequency="regular",
        is_taxable=False,           # mismatched: canonical is True
        counts_for_uif=True,
        counts_for_sdl=True,
        proration_rule="none",
        is_system=False, is_active=True, row_version=1,
    )
    db.add(et); db.flush()
    with pytest.raises(AppError) as exc:
        ensure_base_monthly_type(db)
    assert exc.value.code == "base_monthly_type_config_mismatch"
    assert "field_diffs" in exc.value.details
    assert "is_taxable" in exc.value.details["field_diffs"]


def test_ensure_base_monthly_raises_on_inactive(_leave_session_shared):
    db = _leave_session_shared
    et = EarningType(
        code="BASE_MONTHLY", name="Old base",
        calc_method="fixed_amount",
        frequency="regular",
        is_taxable=True, counts_for_uif=True, counts_for_sdl=True,
        proration_rule="none",
        is_system=False, is_active=False, row_version=1,
    )
    db.add(et); db.flush()
    with pytest.raises(AppError) as exc:
        ensure_base_monthly_type(db)
    assert exc.value.code == "base_monthly_type_inactive"


def test_ensure_base_monthly_never_overwrites_existing(_leave_session_shared):
    """Even when create is a no-op, the existing row's fields are untouched."""
    db = _leave_session_shared
    original_name = "Custom Name"
    et = EarningType(
        code="BASE_MONTHLY", name=original_name,
        calc_method="fixed_amount",
        frequency="regular",
        is_taxable=True, counts_for_uif=True, counts_for_sdl=True,
        proration_rule="none",
        is_system=False, is_active=True, row_version=1,
    )
    db.add(et); db.flush()
    original_id = et.id
    returned = ensure_base_monthly_type(db)
    assert returned.id == original_id
    assert returned.name == original_name

# END OF FILE