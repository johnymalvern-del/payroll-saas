"""Branch CRUD, list, deactivate, reactivate, delete (1C.5).

Every endpoint is tenant-scoped (via TenantDbDep) and permission-checked
(ORG_VIEW for reads, ORG_MANAGE for writes) and scope-checked via
`apply_branch_scope` (list) or `assert_branch_in_scope` (single-row). Scope
violations return 404 record_not_found, not 403, so a user outside scope
cannot distinguish "does not exist" from "exists but not yours" - that is
the standard IDOR mitigation and matches the guidance in app/core/scope.py.

List envelope is the codebase standard:
    {"items": [...], "next_cursor": "..."}
with ?include_total=true adding "total". Default limit 100, max 500.

Filters: name (contains, case-insensitive), code (exact, case-insensitive
via lower()), is_active (bool). By default only active branches are
returned; ?include_inactive=true shows all.

Error codes:
  duplicate_code          - branch code exists (case-insensitive, trimmed)
  branch_has_active_sites - deactivate refused: active sites still reference it
  branch_in_use           - delete refused: sites or employees reference it
  record_changed          - row_version mismatch on PATCH
  record_not_found        - branch not found, or outside scope (see above)
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
from app.api.v1.branches_schemas import (
    BranchCreateIn,
    BranchListOut,
    BranchOut,
    BranchPatchIn,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import (
    ScopeViolation,
    apply_branch_scope,
    assert_branch_in_scope,
)
from app.db.tenant.models.organisation import Branch, Site
from app.db.tenant.models.people import Employee
from app.db.tenant.models.platform import AuditLog
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix="/branches", tags=["branches"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _to_out(b: Branch) -> BranchOut:
    return BranchOut(
        id=b.id,
        name=b.name,
        code=b.code,
        address=b.address,
        is_active=b.is_active,
        row_version=b.row_version,
    )


def _encode_cursor(created_at: datetime, branch_id: uuid.UUID) -> str:
    payload = {"c": created_at.isoformat(), "i": str(branch_id)}
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
        branch_id = uuid.UUID(payload["i"])
        return created_at, branch_id
    except Exception:
        raise AppError(
            "invalid_cursor",
            "The pagination cursor is malformed",
            status.HTTP_400_BAD_REQUEST,
        ) from None


def _scope_violation_as_not_found() -> AppError:
    return AppError(
        "record_not_found",
        "Branch not found",
        status.HTTP_404_NOT_FOUND,
    )


@router.get("", response_model=BranchListOut)
def list_branches(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ORG_VIEW))],
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
    include_inactive: bool = Query(False),
    include_total: bool = Query(False),
    name: str | None = Query(None),
    code: str | None = Query(None),
    is_active: bool | None = Query(None),
) -> BranchListOut:
    q = select(Branch)
    if not include_inactive:
        q = q.where(Branch.is_active.is_(True))
    if is_active is not None:
        q = q.where(Branch.is_active.is_(is_active))
    if name is not None:
        q = q.where(func.lower(Branch.name).like(f"%{name.strip().lower()}%"))
    if code is not None:
        q = q.where(func.lower(Branch.code) == code.strip().lower())

    q = apply_branch_scope(q, user, db)

    if cursor is not None:
        cursor_ts, cursor_id = _decode_cursor(cursor)
        q = q.where(
            or_(
                Branch.created_at > cursor_ts,
                (Branch.created_at == cursor_ts) & (Branch.id > cursor_id),
            )
        )

    q = q.order_by(Branch.created_at.asc(), Branch.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    total: int | None = None
    if include_total:
        tq = select(func.count()).select_from(Branch)
        if not include_inactive:
            tq = tq.where(Branch.is_active.is_(True))
        if is_active is not None:
            tq = tq.where(Branch.is_active.is_(is_active))
        if name is not None:
            tq = tq.where(func.lower(Branch.name).like(f"%{name.strip().lower()}%"))
        if code is not None:
            tq = tq.where(func.lower(Branch.code) == code.strip().lower())
        tq = apply_branch_scope(tq, user, db)
        total = int(db.scalar(tq) or 0)

    return BranchListOut(
        items=[_to_out(r) for r in rows],
        next_cursor=next_cursor,
        total=total,
    )


@router.post("", response_model=BranchOut, status_code=status.HTTP_201_CREATED)
def create_branch(
    payload: BranchCreateIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ORG_MANAGE))],
) -> BranchOut:
    clean_code = payload.code.strip()
    existing = db.scalar(
        select(Branch).where(func.lower(Branch.code) == clean_code.lower())
    )
    if existing is not None:
        raise AppError(
            "duplicate_code",
            f"A branch with code '{clean_code}' already exists",
            status.HTTP_409_CONFLICT,
        )

    branch = Branch(
        name=payload.name,
        code=clean_code,
        address=payload.address,
        is_active=True,
        row_version=1,
    )
    db.add(branch)
    db.flush()

    new_snapshot = _to_out(branch).model_dump(mode="json")
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="branch",
            entity_id=str(branch.id),
            action="branch.create",
            old_value=None,
            new_value=redact_for_audit(new_snapshot),
        )
    )
    db.commit()
    db.refresh(branch)
    return _to_out(branch)


@router.get("/{branch_id}", response_model=BranchOut)
def get_branch(
    branch_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ORG_VIEW))],
) -> BranchOut:
    try:
        assert_branch_in_scope(user, branch_id, db)
    except ScopeViolation:
        raise _scope_violation_as_not_found() from None

    branch = db.get(Branch, branch_id)
    if branch is None:
        raise _scope_violation_as_not_found()
    return _to_out(branch)


@router.patch("/{branch_id}", response_model=BranchOut)
def patch_branch(
    branch_id: uuid.UUID,
    payload: BranchPatchIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ORG_MANAGE))],
) -> BranchOut:
    try:
        assert_branch_in_scope(user, branch_id, db)
    except ScopeViolation:
        raise _scope_violation_as_not_found() from None

    current = db.get(Branch, branch_id)
    if current is None:
        raise _scope_violation_as_not_found()

    if current.row_version != payload.row_version:
        raise AppError(
            "record_changed",
            f"Branch has changed (current version {current.row_version}); "
            "reload and retry",
            status.HTTP_409_CONFLICT,
            {"current_row_version": current.row_version},
        )

    supplied = payload.model_dump(exclude_unset=True)
    update_fields: dict[str, Any] = {}
    for key in ("name", "address"):
        if key in supplied and supplied[key] is not None:
            update_fields[key] = supplied[key]

    if "code" in supplied and supplied["code"] is not None:
        clean_code = supplied["code"].strip()
        clash = db.scalar(
            select(Branch).where(
                func.lower(Branch.code) == clean_code.lower(),
                Branch.id != current.id,
            )
        )
        if clash is not None:
            raise AppError(
                "duplicate_code",
                f"A branch with code '{clean_code}' already exists",
                status.HTTP_409_CONFLICT,
            )
        update_fields["code"] = clean_code

    if "is_active" in supplied and supplied["is_active"] is not None:
        new_active = bool(supplied["is_active"])
        if current.is_active and not new_active:
            active_sites = int(
                db.scalar(
                    select(func.count()).select_from(Site).where(
                        Site.branch_id == current.id,
                        Site.is_active.is_(True),
                    )
                )
                or 0
            )
            if active_sites > 0:
                raise AppError(
                    "branch_has_active_sites",
                    f"Cannot deactivate branch: {active_sites} active site(s) "
                    "still reference it",
                    status.HTTP_409_CONFLICT,
                    {"active_sites": active_sites},
                )
        update_fields["is_active"] = new_active

    if not update_fields:
        return _to_out(current)

    old_snapshot = _to_out(current).model_dump(mode="json")
    new_version = current.row_version + 1

    stmt = (
        update(Branch)
        .where(Branch.id == current.id, Branch.row_version == payload.row_version)
        .values(**update_fields, row_version=new_version)
    )
    result = db.execute(stmt)
    if result.rowcount == 0:
        db.rollback()
        raise AppError(
            "record_changed",
            "Branch changed during this request; reload and retry",
            status.HTTP_409_CONFLICT,
        )

    db.expire_all()
    db.flush()
    refreshed = db.scalar(select(Branch).where(Branch.id == current.id))
    assert refreshed is not None
    new_snapshot = _to_out(refreshed).model_dump(mode="json")

    if old_snapshot.get("is_active") and not new_snapshot.get("is_active"):
        action = "branch.deactivate"
    elif (not old_snapshot.get("is_active")) and new_snapshot.get("is_active"):
        action = "branch.reactivate"
    else:
        action = "branch.update"

    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="branch",
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
    "/{branch_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_branch(
    branch_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ORG_MANAGE))],
) -> Response:
    try:
        assert_branch_in_scope(user, branch_id, db)
    except ScopeViolation:
        raise _scope_violation_as_not_found() from None

    branch = db.get(Branch, branch_id)
    if branch is None:
        raise _scope_violation_as_not_found()

    site_count = int(
        db.scalar(select(func.count()).select_from(Site).where(Site.branch_id == branch.id))
        or 0
    )
    employee_count = int(
        db.scalar(
            select(func.count()).select_from(Employee).where(
                Employee.branch_id == branch.id
            )
        )
        or 0
    )
    if site_count > 0 or employee_count > 0:
        raise AppError(
            "branch_in_use",
            f"Cannot delete branch: {site_count} site(s) and "
            f"{employee_count} employee(s) reference it",
            status.HTTP_409_CONFLICT,
            {"sites": site_count, "employees": employee_count},
        )

    old_snapshot = _to_out(branch).model_dump(mode="json")
    db.delete(branch)
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="branch",
            entity_id=str(branch.id),
            action="branch.delete",
            old_value=redact_for_audit(old_snapshot),
            new_value=None,
        )
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# END OF FILE