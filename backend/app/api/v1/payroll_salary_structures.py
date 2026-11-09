"""Salary structure endpoints (Chapter 4, Milestone 3, Stage B).

HR creates/edits/deactivates via PAY_RATE_REQUEST.
List/get via PAY_RATE_VIEW (hr, payroll_admin, auditor).
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import TenantDbDep
from app.api.v1.payroll_salary_structures_schemas import (
    DeactivateOut,
    StructureComponentOut,
    StructureCreateIn,
    StructureEditIn,
    StructureListOut,
    StructureOut,
)
from app.core.permissions import Permission, require_permission
from app.services import salary_structure_service as svc

router = APIRouter(
    prefix="/payroll/salary-structures",
    tags=["payroll-salary-structures"],
)


def _serialize(db, structure) -> StructureOut:
    comps = svc.get_structure_components(db, structure.id)
    return StructureOut(
        id=structure.id,
        structure_group_id=structure.structure_group_id,
        version_number=structure.version_number,
        is_current=structure.is_current,
        name=structure.name,
        description=structure.description,
        pay_basis=structure.pay_basis,
        base_rate=structure.base_rate,
        is_active=structure.is_active,
        row_version=structure.row_version,
        created_at=structure.created_at,
        updated_at=structure.updated_at,
        components=[
            StructureComponentOut(
                id=c.id,
                kind=c.kind,
                earning_type_id=c.earning_type_id,
                deduction_type_id=c.deduction_type_id,
                amount=c.amount,
                rate=c.rate,
            )
            for c in comps
        ],
    )


@router.post("", response_model=StructureOut, status_code=201)
def create(
    body: StructureCreateIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> StructureOut:
    s = svc.create_structure(
        db, user,
        name=body.name,
        description=body.description,
        pay_basis=body.pay_basis,
        base_rate=body.base_rate,
        components=[c.model_dump() for c in body.components],
    )
    db.commit()
    return _serialize(db, s)


@router.get("", response_model=StructureListOut)
def list_structures(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_VIEW))],
) -> StructureListOut:
    rows = svc.list_current_structures(db)
    return StructureListOut(items=[_serialize(db, s) for s in rows])


@router.get("/{group_id}", response_model=StructureOut)
def get_current(
    group_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_VIEW))],
) -> StructureOut:
    s = svc.get_current_structure(db, group_id)
    return _serialize(db, s)


@router.get("/{group_id}/versions", response_model=StructureListOut)
def list_versions(
    group_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_VIEW))],
) -> StructureListOut:
    rows = svc.list_versions(db, group_id)
    return StructureListOut(items=[_serialize(db, s) for s in rows])


@router.get("/{group_id}/versions/{n}", response_model=StructureOut)
def get_version(
    group_id: uuid.UUID,
    n: int,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_VIEW))],
) -> StructureOut:
    s = svc.get_version(db, group_id, n)
    return _serialize(db, s)


@router.patch("/{group_id}", response_model=StructureOut)
def edit(
    group_id: uuid.UUID,
    body: StructureEditIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> StructureOut:
    comps = None
    if body.components is not None:
        comps = [c.model_dump() for c in body.components]
    s = svc.edit_structure(
        db, user, group_id,
        version_number=body.version_number,
        row_version=body.row_version,
        name=body.name,
        description=body.description,
        pay_basis=body.pay_basis,
        base_rate=body.base_rate,
        components=comps,
    )
    db.commit()
    return _serialize(db, s)


@router.post("/{group_id}/deactivate", response_model=DeactivateOut)
def deactivate(
    group_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> DeactivateOut:
    svc.deactivate_group(db, user, group_id)
    db.commit()
    return DeactivateOut(structure_group_id=group_id)

# END OF FILE