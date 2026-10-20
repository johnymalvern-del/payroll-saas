"""FastAPI dependency helpers.

- `ControlDbDep`  : a control-database session (platform admin, registration)
- `TenantDep`     : a resolved TenantContext (raises if the request has no tenant)
- `TenantDbDep`   : a tenant-database session, scoped to the resolved tenant
- `CurrentUser`   : populated in Phase 1C (auth); left as a type alias here.

Every endpoint that touches tenant data must depend on `TenantDbDep` (which
implies `TenantDep`). Endpoints that touch the control DB use `ControlDbDep`.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.tenant_routing import (
    TenantContext,
    TenantError,
    TenantInactive,
    TenantNotProvisioned,
    TenantNotFound,
    TenantNotSpecified,
    TenantSchemaBehind,
    resolve_slug,
    tenant_context,
)
from app.db.control.session import control_session
from app.db.tenant.session import tenant_session

log = get_logger("app.api.deps")


# ---------------------------------------------------------------------------
# Control DB session
# ---------------------------------------------------------------------------


def _control_db() -> Iterator[Session]:
    with control_session() as session:
        yield session


ControlDbDep = Annotated[Session, Depends(_control_db)]


# ---------------------------------------------------------------------------
# Tenant context
# ---------------------------------------------------------------------------


def _translate_tenant_error(exc: TenantError) -> AppError:
    if isinstance(exc, TenantNotSpecified):
        return AppError(
            "tenant_missing",
            "Tenant not specified (provide subdomain or X-Tenant-Slug)",
            status.HTTP_400_BAD_REQUEST,
        )
    if isinstance(exc, TenantNotFound):
        return AppError(
            "tenant_not_found", f"Tenant '{exc.slug}' not found", status.HTTP_404_NOT_FOUND
        )
    if isinstance(exc, TenantInactive):
        return AppError(
            "tenant_inactive",
            f"Tenant '{exc.slug}' is {exc.status}",
            status.HTTP_403_FORBIDDEN,
        )
    if isinstance(exc, TenantNotProvisioned):
        return AppError(
            "tenant_not_provisioned",
            f"Tenant '{exc.slug}' is not yet provisioned",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, TenantSchemaBehind):
        return AppError(
            "tenant_schema_behind",
            f"Tenant '{exc.slug}' requires a migration ({exc.current!r} -> {exc.expected!r})",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return AppError(
        "tenant_error", str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR
    )


def _tenant(request: Request) -> Iterator[TenantContext]:
    slug = resolve_slug(request)
    if slug is None:
        raise _translate_tenant_error(TenantNotSpecified())
    try:
        with tenant_context(slug) as ctx:
            yield ctx
    except TenantError as exc:
        raise _translate_tenant_error(exc) from exc


TenantDep = Annotated[TenantContext, Depends(_tenant)]


# ---------------------------------------------------------------------------
# Tenant DB session (implies tenant context)
# ---------------------------------------------------------------------------


def _tenant_db(ctx: TenantDep) -> Iterator[Session]:
    with tenant_session(ctx.tenant_db_name) as session:
        yield session


TenantDbDep = Annotated[Session, Depends(_tenant_db)]


# ---------------------------------------------------------------------------
# Placeholders for Phase 1C
# ---------------------------------------------------------------------------


# `CurrentUser` will be replaced with an Annotated dependency in Phase 1C:
#   CurrentUser = Annotated[User, Depends(get_current_user)]
# For now, tests that need auth simply bypass it.


def ensure_no_tenant(request: Request) -> None:
    """Raise if the request is carrying a tenant. Used by platform endpoints."""
    if resolve_slug(request) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint must not be called for a specific tenant",
        )