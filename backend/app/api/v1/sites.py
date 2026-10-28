"""Site CRUD, list, deactivate, reactivate, delete (1C.6).

Every endpoint is tenant-scoped (TenantDbDep), permission-checked (ORG_VIEW
for reads, ORG_MANAGE for writes) and scope-checked via apply_site_scope
(list) or assert_site_in_scope (single-row). Scope violations and missing
rows both return 404 record_not_found (IDOR mitigation).

List envelope is the codebase standard:
    {"items": [...], "next_cursor": "..."}
with ?include_total=true adding "total". Default limit 100, max 500.

Filters: branch_id, site_type, is_active.

Error codes:
  duplicate_code   - site code exists (case-insensitive, trimmed)
  invalid_branch   - branch_id missing or inactive (create and patch)
  branch_inactive  - reactivation refused: the site's branch is inactive
  site_in_use      - delete refused: employees reference it
  record_changed   - row_version mismatch on PATCH
  record_not_found - site not found, or outside scope

1C.8 must add: PATCH is_active=false must be refused with 409
site_has_active_employees when any active employee still references the
site. That guard is NOT in this file yet because the employee management
endpoint does not exist; the Employee.site_id column does exist, so the
guard can be added here without a schema change.
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select, update

from app.api.deps import TenantDbDep
from app.api.v1.sites_schemas import (
    SiteCreateIn,
    SiteListOut,
    SiteOut,
    SitePatchIn,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import (
    ScopeViolation,
    apply_site_scope,
    assert_branch_in_scope,
    assert_site_in_scope,
)
from app.db.tenant.models.organisation import Branch, Site
from app.db.tenant.models.attendance import Punch
from app.db.tenant.models.devices import Device
from app.db.tenant.models.people import Employee
from app.db.tenant.models.platform import AuditLog
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix="/sites", tags=["sites"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _to_out(s: Site) -> SiteOut:
    return SiteOut(
        id=s.id,
        branch_id=s.branch_id,
        name=s.name,
        code=s.code,
        site_type=s.site_type,
        address=s.address,
        timezone=s.timezone,
        latitude=float(s.latitude) if s.latitude is not None else None,
        longitude=float(s.longitude) if s.longitude is not None else None,
        geofence_radius_m=s.geofence_radius_m,
        is_active=s.is_active,
        row_version=s.row_version,
    )


def _encode_cursor(created_at: datetime, site_id: uuid.UUID) -> str:
    payload = {"c": created_at.isoformat(), "i": str(site_id)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        created_at = datetime.fromisoformat(payload["c"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        site_id = uuid.UUID(payload["i"])
        return created_at, site_id
    except Exception:
        raise AppError(
            "invalid_cursor",
            "The pagination cursor is malformed",
            status.HTTP_400_BAD_REQUEST,
        ) from None


def _not_found() -> AppError:
    return AppError("record_not_found", "Site not found", status.HTTP_404_NOT_FOUND)


def _validate_branch_for_write(db: Any, user: Any, branch_id: uuid.UUID) -> Branch:
    """Return the branch if it exists, is active, and is in the caller's scope.

    Errors are ordered so that the least informative is returned first:
    a caller who cannot see the branch gets invalid_branch (not
    record_not_found), matching the create-time error shape. This is a
    write path where we accept a small information leak (the caller learns
    that a branch id is invalid, whether by absence, inactivity, or scope)
    because the branch id is not the resource the caller is editing, and
    the site payload already names it.
    """
    branch = db.get(Branch, branch_id)
    if branch is None:
        raise AppError(
            "invalid_branch",
            f"Branch {branch_id} does not exist",
            status.HTTP_400_BAD_REQUEST,
            {"branch_id": str(branch_id)},
        )
    if not branch.is_active:
        raise AppError(
            "invalid_branch",
            f"Branch {branch_id} is inactive; new or reassigned sites "
            "must belong to an active branch",
            status.HTTP_400_BAD_REQUEST,
            {"branch_id": str(branch_id)},
        )
    try:
        assert_branch_in_scope(user, branch_id, db)
    except ScopeViolation:
        raise AppError(
            "invalid_branch",
            f"Branch {branch_id} is not available to the current user",
            status.HTTP_400_BAD_REQUEST,
            {"branch_id": str(branch_id)},
        ) from None
    return branch


@router.get("", response_model=SiteListOut)
def list_sites(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ORG_VIEW))],
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
    include_inactive: bool = Query(False),
    include_total: bool = Query(False),
    branch_id: uuid.UUID | None = Query(None),
    site_type: str | None = Query(None),
    is_active: bool | None = Query(None),
) -> SiteListOut:
    q = select(Site)
    if not include_inactive:
        q = q.where(Site.is_active.is_(True))
    if is_active is not None:
        q = q.where(Site.is_active.is_(is_active))
    if branch_id is not None:
        q = q.where(Site.branch_id == branch_id)
    if site_type is not None:
        q = q.where(Site.site_type == site_type)

    q = apply_site_scope(q, user, db)

    if cursor is not None:
        cursor_ts, cursor_id = _decode_cursor(cursor)
        q = q.where(
            or_(
                Site.created_at > cursor_ts,
                (Site.created_at == cursor_ts) & (Site.id > cursor_id),
            )
        )

    q = q.order_by(Site.created_at.asc(), Site.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    total: int | None = None
    if include_total:
        tq = select(func.count()).select_from(Site)
        if not include_inactive:
            tq = tq.where(Site.is_active.is_(True))
        if is_active is not None:
            tq = tq.where(Site.is_active.is_(is_active))
        if branch_id is not None:
            tq = tq.where(Site.branch_id == branch_id)
        if site_type is not None:
            tq = tq.where(Site.site_type == site_type)
        tq = apply_site_scope(tq, user, db)
        total = int(db.scalar(tq) or 0)

    return SiteListOut(
        items=[_to_out(r) for r in rows],
        next_cursor=next_cursor,
        total=total,
    )


@router.post("", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
def create_site(
    payload: SiteCreateIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ORG_MANAGE))],
) -> SiteOut:
    branch = _validate_branch_for_write(db, user, payload.branch_id)

    clean_code = payload.code.strip()
    existing = db.scalar(
        select(Site).where(func.lower(Site.code) == clean_code.lower())
    )
    if existing is not None:
        raise AppError(
            "duplicate_code",
            f"A site with code '{clean_code}' already exists",
            status.HTTP_409_CONFLICT,
        )

    site = Site(
        branch_id=branch.id,
        name=payload.name,
        code=clean_code,
        site_type=payload.site_type,
        address=payload.address,
        timezone=payload.timezone,
        latitude=payload.latitude,
        longitude=payload.longitude,
        geofence_radius_m=payload.geofence_radius_m,
        is_active=True,
        row_version=1,
    )
    db.add(site)
    db.flush()

    new_snapshot = _to_out(site).model_dump(mode="json")
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="site",
            entity_id=str(site.id),
            action="site.create",
            old_value=None,
            new_value=redact_for_audit(new_snapshot),
        )
    )
    db.commit()
    db.refresh(site)
    return _to_out(site)


@router.get("/{site_id}", response_model=SiteOut)
def get_site(
    site_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ORG_VIEW))],
) -> SiteOut:
    try:
        assert_site_in_scope(user, site_id, db)
    except ScopeViolation:
        raise _not_found() from None

    site = db.get(Site, site_id)
    if site is None:
        raise _not_found()
    return _to_out(site)


@router.patch("/{site_id}", response_model=SiteOut)
def patch_site(
    site_id: uuid.UUID,
    payload: SitePatchIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ORG_MANAGE))],
) -> SiteOut:
    try:
        assert_site_in_scope(user, site_id, db)
    except ScopeViolation:
        raise _not_found() from None

    current = db.get(Site, site_id)
    if current is None:
        raise _not_found()

    if current.row_version != payload.row_version:
        raise AppError(
            "record_changed",
            f"Site has changed (current version {current.row_version}); "
            "reload and retry",
            status.HTTP_409_CONFLICT,
            {"current_row_version": current.row_version},
        )

    supplied = payload.model_dump(exclude_unset=True)
    update_fields: dict[str, Any] = {}

    for key in ("name", "site_type", "address", "timezone",
                "latitude", "longitude", "geofence_radius_m"):
        if key in supplied and supplied[key] is not None:
            update_fields[key] = supplied[key]

    if "branch_id" in supplied and supplied["branch_id"] is not None:
        new_branch_id = supplied["branch_id"]
        _validate_branch_for_write(db, user, new_branch_id)
        update_fields["branch_id"] = new_branch_id

    if "code" in supplied and supplied["code"] is not None:
        clean_code = supplied["code"].strip()
        clash = db.scalar(
            select(Site).where(
                func.lower(Site.code) == clean_code.lower(),
                Site.id != current.id,
            )
        )
        if clash is not None:
            raise AppError(
                "duplicate_code",
                f"A site with code '{clean_code}' already exists",
                status.HTTP_409_CONFLICT,
            )
        update_fields["code"] = clean_code

    if "is_active" in supplied and supplied["is_active"] is not None:
        new_active = bool(supplied["is_active"])
        if (not current.is_active) and new_active:
            # Reactivation guard: the site's branch must still be active.
            branch_of_site = db.get(Branch, current.branch_id)
            if branch_of_site is None or not branch_of_site.is_active:
                raise AppError(
                    "branch_inactive",
                    "Cannot reactivate site: its branch is inactive",
                    status.HTTP_409_CONFLICT,
                    {"branch_id": str(current.branch_id)},
                )
        update_fields["is_active"] = new_active

    if not update_fields:
        return _to_out(current)

    old_snapshot = _to_out(current).model_dump(mode="json")
    new_version = current.row_version + 1

    stmt = (
        update(Site)
        .where(Site.id == current.id, Site.row_version == payload.row_version)
        .values(**update_fields, row_version=new_version)
    )
    result = db.execute(stmt)
    if result.rowcount == 0:
        db.rollback()
        raise AppError(
            "record_changed",
            "Site changed during this request; reload and retry",
            status.HTTP_409_CONFLICT,
        )

    db.expire_all()
    db.flush()
    refreshed = db.scalar(select(Site).where(Site.id == current.id))
    assert refreshed is not None
    new_snapshot = _to_out(refreshed).model_dump(mode="json")

    if old_snapshot.get("is_active") and not new_snapshot.get("is_active"):
        action = "site.deactivate"
    elif (not old_snapshot.get("is_active")) and new_snapshot.get("is_active"):
        action = "site.reactivate"
    else:
        action = "site.update"

    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="site",
            entity_id=str(current.id),
            action=action,
            old_value=redact_for_audit(old_snapshot),
            new_value=redact_for_audit(new_snapshot),
        )
    )
    db.commit()
    db.refresh(refreshed)
    return _to_out(refreshed)


@router.delete(
    "/{site_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_site(
    site_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ORG_MANAGE))],
) -> Response:
    try:
        assert_site_in_scope(user, site_id, db)
    except ScopeViolation:
        raise _not_found() from None

    site = db.get(Site, site_id)
    if site is None:
        raise _not_found()

    employee_count = int(
        db.scalar(
            select(func.count()).select_from(Employee).where(
                Employee.site_id == site.id
            )
        )
        or 0
    )
    punch_count = int(
        db.scalar(select(func.count()).select_from(Punch).where(Punch.site_id == site.id))
        or 0
    )
    device_count = int(
        db.scalar(select(func.count()).select_from(Device).where(Device.site_id == site.id))
        or 0
    )
    if employee_count > 0 or punch_count > 0 or device_count > 0:
        raise AppError(
            "site_in_use",
            f"Cannot delete site: employees={employee_count}, punches={punch_count}, devices={device_count}",
            status.HTTP_409_CONFLICT,
            {"employees": employee_count, "punches": punch_count, "devices": device_count},
        )

    old_snapshot = _to_out(site).model_dump(mode="json")
    db.delete(site)
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="site",
            entity_id=str(site.id),
            action="site.delete",
            old_value=redact_for_audit(old_snapshot),
            new_value=None,
        )
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# END OF FILE