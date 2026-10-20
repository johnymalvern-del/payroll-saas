"""Public tenant registration endpoint.

Creates a new subscriber, provisions its tenant database, seeds the first
admin user, and returns the schema version that was applied.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import ensure_no_tenant
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.security import hash_password, password_meets_policy
from app.services.provisioning import ProvisioningError, provision_tenant

router = APIRouter(
    prefix="/register",
    tags=["registration"],
    dependencies=[Depends(ensure_no_tenant)],
)
log = get_logger("app.api.v1.register")


class RegisterIn(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=2, max_length=60)
    admin_username: str = Field(..., min_length=3, max_length=120)
    admin_password: str = Field(..., min_length=12, max_length=200)
    admin_email: EmailStr | None = None


class RegisterOut(BaseModel):
    subscriber_id: str
    slug: str
    tenant_db_name: str
    schema_version: str
    message: str


@router.post("", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn) -> RegisterOut:
    ok, reason = password_meets_policy(payload.admin_password)
    if not ok:
        raise AppError("weak_password", reason or "Password too weak", status.HTTP_400_BAD_REQUEST)

    log.info("register.requested", slug=payload.slug, company=payload.company_name)

    try:
        result = provision_tenant(
            slug=payload.slug,
            name=payload.company_name,
            admin_username=payload.admin_username,
            admin_password_hash=hash_password(payload.admin_password),
        )
    except ProvisioningError as exc:
        raise AppError(
            "provisioning_failed", str(exc), status.HTTP_400_BAD_REQUEST
        ) from exc

    log.info(
        "register.completed",
        slug=result.slug,
        subscriber_id=str(result.subscriber_id),
        schema_version=result.schema_version,
    )
    return RegisterOut(
        subscriber_id=str(result.subscriber_id),
        slug=result.slug,
        tenant_db_name=result.tenant_db_name,
        schema_version=result.schema_version,
        message="Tenant provisioned. First login must change the password.",
    )