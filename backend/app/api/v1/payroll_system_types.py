"""System earning types management (Chapter 4, Bundle 004a-iv-c)."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import TenantDbDep
from app.core.permissions import Permission, require_permission
from app.services.payroll_seed import ensure_system_earning_types

router = APIRouter(prefix="/payroll", tags=["payroll-system-types"])


@router.post("/earning-types/ensure-system")
def ensure_system_types_endpoint(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_FINALISE))],
) -> dict:
    result = ensure_system_earning_types(db)
    db.commit()
    return result

# END OF FILE
