"""Leave accrual run endpoint (Chapter 3, 3B.3).

Amendment 3: GET endpoints never write. Accruals are materialised only by
POST /leave/accruals/run (USER_MANAGE) and by the daily-jobs CLI. GET
/leave/balances surfaces `accrued_as_of` and `accrual_stale` so the
caller can tell when the last run happened.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import TenantDbDep
from app.api.v1.leave_accruals_schemas import AccrualRunIn, AccrualRunOut
from app.core.permissions import Permission, require_permission
from app.payroll_engine.leave import accrue_all_employees

router = APIRouter(prefix="/leave/accruals", tags=["leave-accruals"])


@router.post("/run", response_model=AccrualRunOut)
def run_accruals(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.USER_MANAGE))],
    body: AccrualRunIn | None = None,
) -> AccrualRunOut:
    as_of = body.as_of_date if body and body.as_of_date else date.today()
    result = accrue_all_employees(db, as_of)
    return AccrualRunOut(**result)