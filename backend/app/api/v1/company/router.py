
"""Company CRUD - single-row resource."""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from sqlalchemy import select, update

from app.api.deps import TenantDbDep
from app.api.v1.company.schemas import (
    PAYROLL_ADMIN_ONLY_FIELDS,
    CompanyOut,
    CompanyPatchIn,
)
from app.core.auth_deps import get_current_user
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.db.tenant.models.organisation import Company
from app.db.tenant.models.platform import AuditLog
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix="/company", tags=["company"])


def _to_out(c: Company) -> CompanyOut:
    return CompanyOut(
        id=c.id,
        legal_name=c.legal_name,
        trading_name=c.trading_name,
        registration_number=c.registration_number,
        tax_number=c.tax_number,
        paye_reference=c.paye_reference,
        uif_reference=c.uif_reference,
        sdl_reference=c.sdl_reference,
        coida_reference=c.coida_reference,
        address=c.address,
        country_code=c.country_code,
        currency=c.currency,
        default_timezone=c.default_timezone,
        settings=c.settings or {},
        row_version=c.row_version,
    )


@router.get("", response_model=CompanyOut)
def get_company(
    db: TenantDbDep,
    _user: Annotated[Any, Depends(require_permission(Permission.SELF_VIEW))],
) -> CompanyOut:
    company = db.scalar(select(Company))
    if company is None:
        raise AppError(
            "company_missing",
            "Company row not found; tenant is not provisioned",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return _to_out(company)


@router.patch("", response_model=CompanyOut)
def patch_company(
    payload: CompanyPatchIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SELF_VIEW))],
) -> CompanyOut:
    if user.role not in ("hr", "payroll_admin"):
        raise AppError(
            "forbidden",
            "Only HR or payroll admin may edit company data",
            status.HTTP_403_FORBIDDEN,
        )

    supplied = payload.model_dump(exclude_unset=True)
    if user.role == "hr":
        forbidden = PAYROLL_ADMIN_ONLY_FIELDS & set(supplied.keys())
        if forbidden:
            raise AppError(
                "forbidden_field",
                f"Only payroll_admin may edit: {', '.join(sorted(forbidden))}",
                status.HTTP_403_FORBIDDEN,
                {"fields": sorted(forbidden)},
            )

    current = db.scalar(select(Company))
    if current is None:
        raise AppError(
            "company_missing",
            "Company row not found",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if current.row_version != payload.row_version:
        raise AppError(
            "record_changed",
            f"Company row has changed (current version {current.row_version}); reload and retry",
            status.HTTP_409_CONFLICT,
            {"current_row_version": current.row_version},
        )

    update_fields = {k: v for k, v in supplied.items() if k != "row_version"}
    if not update_fields:
        return _to_out(current)

    # IMPORTANT: capture the OLD snapshot before running the UPDATE, because
    # `current` is an ORM-attached object and `db.execute(update(...))` will
    # not refresh it automatically, but the second `db.get(...)` after the
    # update will return the NEW values. Capturing `old_snapshot` here, from
    # the in-memory object BEFORE any mutation, is correct.
    old_snapshot = _to_out(current).model_dump(mode="json")

    new_version = current.row_version + 1
    stmt = (
        update(Company)
        .where(Company.id == current.id, Company.row_version == payload.row_version)
        .values(**update_fields, row_version=new_version)
    )
    result = db.execute(stmt)
    if result.rowcount == 0:
        db.rollback()
        raise AppError(
            "record_changed",
            "Company row changed during this request; reload and retry",
            status.HTTP_409_CONFLICT,
        )

    # Refresh the ORM state from the DB so new_snapshot reflects the write.
    db.expire_all()
    db.flush()
    refreshed = db.scalar(select(Company))
    assert refreshed is not None
    new_snapshot = _to_out(refreshed).model_dump(mode="json")

    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="company",
            entity_id=str(current.id),
            action="company.update",
            old_value=redact_for_audit(old_snapshot),
            new_value=redact_for_audit(new_snapshot),
        )
    )
    db.commit()

    final = db.scalar(select(Company))
    assert final is not None
    return _to_out(final)
