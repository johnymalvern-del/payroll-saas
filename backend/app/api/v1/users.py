"""User CRUD and user_scope assignment (1C.9).

Surface:
  GET    /api/v1/users               list (cursor, filters)
  POST   /api/v1/users               create (admin-create per D1A)
  GET    /api/v1/users/{id}          read
  PATCH  /api/v1/users/{id}          only is_active patchable (D5A); row_version required
  DELETE /api/v1/users/{id}          405 (D6A)
  GET    /api/v1/users/{id}/scopes   current scope rows
  PUT    /api/v1/users/{id}/scopes   replace-all (D3A)

All endpoints require USER_MANAGE, which only payroll_admin holds (per the
permission matrix, unchanged). No apply_scope call is needed because no
other role reaches these endpoints; the permission check fails closed for
everyone else.

Password and identity:
  - password_meets_policy (min 12 chars) enforced on create.
  - hash_password from app.core.security.
  - must_change_password=true on every created user, matching the first
    admin created by provisioning.py.
  - username normalised via normalise_username on write; authenticate()
    normalises on read, so the two agree.
  - ValueError from normalise_username maps to 400 invalid_username with
    the offending value.

Role and employee binding:
  - role must be one of {employee, manager, hr, payroll_admin, auditor}.
  - employee_id, if set, must reference an existing Employee row.
  - One active user per employee (D7A): checked at create and at
    PATCH is_active=true; conflict returns 409 duplicate_employee_user.
    Migration 0009 enforces this at DB level with a partial unique index,
    which is the safety net.

Deactivation (D6A):
  - PATCH is_active=false also revokes every non-revoked RefreshTokenFamily
    for that user with revoked_reason="user_deactivated", mirroring the
    pattern in app/services/auth_service.change_password. The audit entry
    is one row with old/new is_active and the revoked family count.

Errors:
  duplicate_username         - username exists (normalised)
  duplicate_employee_user    - active user already exists for that employee
  invalid_username           - normalise_username rejected the value
  invalid_role               - role not in the allowed set
  invalid_employee           - employee_id does not exist
  invalid_scope              - scope_type not site/branch/department,
                               or scope_id row does not exist
  field_not_patchable        - any field other than is_active on PATCH
  record_changed             - row_version mismatch on PATCH
  record_not_found           - user not found
  method_not_allowed         - DELETE
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select

from app.api.deps import TenantDbDep
from app.api.v1.users_schemas import (
    ALLOWED_ROLES,
    ALLOWED_SCOPE_TYPES,
    USER_PATCH_FORBIDDEN_FIELDS,
    ScopeItemIn,
    ScopeListOut,
    ScopeOut,
    ScopeReplaceIn,
    UserCreateIn,
    UserListOut,
    UserOut,
    UserPatchIn,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.security import hash_password, password_meets_policy
from app.core.usernames import normalise_username
from app.db.tenant.models.organisation import Branch, Department, Site
from app.db.tenant.models.people import Employee, User, UserScope
from app.db.tenant.models.platform import AuditLog
from app.models_auth_orm import RefreshTokenFamily
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix="/users", tags=["users"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _not_found() -> AppError:
    return AppError("record_not_found", "User not found", status.HTTP_404_NOT_FOUND)


def _to_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        username=u.username,
        employee_id=u.employee_id,
        role=u.role,
        is_active=u.is_active,
        must_change_password=u.must_change_password,
        last_login_at=u.last_login_at,
        row_version=u.row_version,
    )


def _encode_cursor(created_at: datetime, user_id: uuid.UUID) -> str:
    payload = {"c": created_at.isoformat(), "i": str(user_id)}
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
        user_id = uuid.UUID(payload["i"])
        return created_at, user_id
    except Exception:
        raise AppError(
            "invalid_cursor",
            "The pagination cursor is malformed",
            status.HTTP_400_BAD_REQUEST,
        ) from None


def _revoke_user_families(db: Any, user_id: uuid.UUID, reason: str) -> int:
    """Revoke every non-revoked RefreshTokenFamily for the user. Return count.

    Mirrors the pattern used by app.services.auth_service.change_password.
    Caller is responsible for the commit.
    """
    families = db.scalars(
        select(RefreshTokenFamily).where(
            RefreshTokenFamily.user_id == user_id,
            RefreshTokenFamily.revoked_at.is_(None),
        )
    ).all()
    now = datetime.now(timezone.utc)
    for fam in families:
        fam.revoked_at = now
        fam.revoked_reason = reason
    return len(families)


def _validate_role(role: str) -> None:
    if role not in ALLOWED_ROLES:
        raise AppError(
            "invalid_role",
            f"role must be one of {ALLOWED_ROLES}",
            status.HTTP_400_BAD_REQUEST,
            {"role": role},
        )


def _validate_employee(db: Any, employee_id: uuid.UUID) -> Employee:
    emp = db.get(Employee, employee_id)
    if emp is None:
        raise AppError(
            "invalid_employee",
            f"Employee {employee_id} does not exist",
            status.HTTP_400_BAD_REQUEST,
            {"employee_id": str(employee_id)},
        )
    return emp


def _active_user_for_employee(
    db: Any, employee_id: uuid.UUID, *, exclude_id: uuid.UUID | None = None
) -> User | None:
    stmt = select(User).where(
        User.employee_id == employee_id,
        User.is_active.is_(True),
    )
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return db.scalar(stmt)


@router.get("", response_model=UserListOut)
def list_users(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.USER_MANAGE))],
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
    include_total: bool = Query(False),
    include_inactive: bool = Query(False),
    role: str | None = Query(None),
    employee_id: uuid.UUID | None = Query(None),
    is_active: bool | None = Query(None),
    has_scope_rows: bool | None = Query(None),
) -> UserListOut:
    q = select(User)
    if not include_inactive:
        q = q.where(User.is_active.is_(True))
    if is_active is not None:
        q = q.where(User.is_active.is_(is_active))
    if role is not None:
        q = q.where(User.role == role)
    if employee_id is not None:
        q = q.where(User.employee_id == employee_id)
    if has_scope_rows is not None:
        sub = select(UserScope.user_id).distinct()
        if has_scope_rows:
            q = q.where(User.id.in_(sub))
        else:
            q = q.where(~User.id.in_(sub))

    if cursor is not None:
        cursor_ts, cursor_id = _decode_cursor(cursor)
        q = q.where(
            or_(
                User.created_at > cursor_ts,
                (User.created_at == cursor_ts) & (User.id > cursor_id),
            )
        )

    q = q.order_by(User.created_at.asc(), User.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    total: int | None = None
    if include_total:
        tq = select(func.count()).select_from(User)
        if not include_inactive:
            tq = tq.where(User.is_active.is_(True))
        if is_active is not None:
            tq = tq.where(User.is_active.is_(is_active))
        if role is not None:
            tq = tq.where(User.role == role)
        if employee_id is not None:
            tq = tq.where(User.employee_id == employee_id)
        if has_scope_rows is not None:
            sub = select(UserScope.user_id).distinct()
            if has_scope_rows:
                tq = tq.where(User.id.in_(sub))
            else:
                tq = tq.where(~User.id.in_(sub))
        total = int(db.scalar(tq) or 0)

    return UserListOut(
        items=[_to_out(r) for r in rows],
        next_cursor=next_cursor,
        total=total,
    )


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.USER_MANAGE))],
) -> UserOut:
    try:
        normalised_username = normalise_username(payload.username)
    except ValueError as exc:
        raise AppError(
            "invalid_username",
            str(exc),
            status.HTTP_400_BAD_REQUEST,
            {"username": payload.username},
        ) from None

    ok, msg = password_meets_policy(payload.password)
    if not ok:
        raise AppError(
            "invalid_password",
            msg or "Password does not meet policy",
            status.HTTP_400_BAD_REQUEST,
        )

    _validate_role(payload.role)

    if payload.employee_id is not None:
        _validate_employee(db, payload.employee_id)
        if payload.is_active:
            existing = _active_user_for_employee(db, payload.employee_id)
            if existing is not None:
                raise AppError(
                    "duplicate_employee_user",
                    f"Employee {payload.employee_id} already has an active "
                    f"user (id={existing.id})",
                    status.HTTP_409_CONFLICT,
                    {"employee_id": str(payload.employee_id)},
                )

    clash = db.scalar(
        select(User).where(func.lower(User.username) == normalised_username.lower())
    )
    if clash is not None:
        raise AppError(
            "duplicate_username",
            f"A user with username '{normalised_username}' already exists",
            status.HTTP_409_CONFLICT,
            {"username": normalised_username},
        )

    new_user = User(
        username=normalised_username,
        password_hash=hash_password(payload.password),
        employee_id=payload.employee_id,
        role=payload.role,
        is_active=payload.is_active,
        must_change_password=True,
        failed_attempts=0,
        row_version=1,
    )
    db.add(new_user)
    db.flush()

    snapshot = _to_out(new_user).model_dump(mode="json")
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="user",
            entity_id=str(new_user.id),
            action="user.create",
            old_value=None,
            new_value=redact_for_audit(snapshot),
        )
    )
    db.commit()
    db.refresh(new_user)
    return _to_out(new_user)


def _validate_scope_entry(db: Any, scope_type: str, scope_id: uuid.UUID) -> None:
    if scope_type not in ALLOWED_SCOPE_TYPES:
        raise AppError(
            "invalid_scope",
            f"scope_type must be one of {ALLOWED_SCOPE_TYPES}",
            status.HTTP_400_BAD_REQUEST,
            {"scope_type": scope_type, "scope_id": str(scope_id)},
        )
    if scope_type == "site":
        row = db.get(Site, scope_id)
    elif scope_type == "branch":
        row = db.get(Branch, scope_id)
    else:
        row = db.get(Department, scope_id)
    if row is None:
        raise AppError(
            "invalid_scope",
            f"{scope_type} {scope_id} does not exist",
            status.HTTP_400_BAD_REQUEST,
            {"scope_type": scope_type, "scope_id": str(scope_id)},
        )


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.USER_MANAGE))],
) -> UserOut:
    current = db.get(User, user_id)
    if current is None:
        raise _not_found()
    return _to_out(current)


@router.patch("/{user_id}", response_model=UserOut)
def patch_user(
    user_id: uuid.UUID,
    payload: UserPatchIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.USER_MANAGE))],
) -> UserOut:
    current = db.get(User, user_id)
    if current is None:
        raise _not_found()

    if current.row_version != payload.row_version:
        raise AppError(
            "record_changed",
            f"User has changed (current version {current.row_version}); "
            "reload and retry",
            status.HTTP_409_CONFLICT,
            {"current_row_version": current.row_version},
        )

    supplied = payload.model_dump(exclude_unset=True)
    forbidden = USER_PATCH_FORBIDDEN_FIELDS & set(supplied.keys())
    if forbidden:
        raise AppError(
            "field_not_patchable",
            f"The following fields cannot be changed via PATCH: "
            f"{', '.join(sorted(forbidden))}",
            status.HTTP_400_BAD_REQUEST,
            {"fields": sorted(forbidden)},
        )

    if "is_active" not in supplied or supplied["is_active"] is None:
        return _to_out(current)

    new_active = bool(supplied["is_active"])
    if new_active and not current.is_active and current.employee_id is not None:
        other = _active_user_for_employee(
            db, current.employee_id, exclude_id=current.id
        )
        if other is not None:
            raise AppError(
                "duplicate_employee_user",
                f"Employee {current.employee_id} already has an active user "
                f"(id={other.id})",
                status.HTTP_409_CONFLICT,
                {"employee_id": str(current.employee_id)},
            )

    old_snapshot = _to_out(current).model_dump(mode="json")
    was_active = current.is_active
    current.is_active = new_active
    current.row_version = current.row_version + 1

    revoked_count = 0
    if was_active and not new_active:
        revoked_count = _revoke_user_families(db, current.id, "user_deactivated")

    db.flush()
    new_snapshot = _to_out(current).model_dump(mode="json")
    audit_new = dict(new_snapshot)
    audit_new["revoked_family_count"] = revoked_count

    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="user",
            entity_id=str(current.id),
            action="user.deactivate" if not new_active else "user.reactivate",
            old_value=redact_for_audit(old_snapshot),
            new_value=redact_for_audit(audit_new),
        )
    )
    db.commit()
    db.refresh(current)
    return _to_out(current)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
    response_class=Response,
    response_model=None,
)
def delete_user(
    user_id: uuid.UUID,
    user: Annotated[Any, Depends(require_permission(Permission.USER_MANAGE))],
) -> Response:
    raise AppError(
        "method_not_allowed",
        "Users cannot be deleted; deactivate via PATCH is_active=false",
        status.HTTP_405_METHOD_NOT_ALLOWED,
    )


@router.get("/{user_id}/scopes", response_model=ScopeListOut)
def get_user_scopes(
    user_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.USER_MANAGE))],
) -> ScopeListOut:
    current = db.get(User, user_id)
    if current is None:
        raise _not_found()
    rows = db.scalars(
        select(UserScope)
        .where(UserScope.user_id == current.id)
        .order_by(UserScope.scope_type.asc(), UserScope.scope_id.asc())
    ).all()
    return ScopeListOut(
        items=[
            ScopeOut(id=r.id, scope_type=r.scope_type, scope_id=r.scope_id)
            for r in rows
        ]
    )


@router.put("/{user_id}/scopes", response_model=ScopeListOut)
def put_user_scopes(
    user_id: uuid.UUID,
    payload: ScopeReplaceIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.USER_MANAGE))],
) -> ScopeListOut:
    current = db.get(User, user_id)
    if current is None:
        raise _not_found()

    seen: set[tuple[str, uuid.UUID]] = set()
    validated: list[tuple[str, uuid.UUID]] = []
    for item in payload.items:
        key = (item.scope_type, item.scope_id)
        if key in seen:
            continue
        seen.add(key)
        _validate_scope_entry(db, item.scope_type, item.scope_id)
        validated.append(key)

    old_rows = db.scalars(
        select(UserScope).where(UserScope.user_id == current.id)
    ).all()
    old_snapshot = [
        {"scope_type": r.scope_type, "scope_id": str(r.scope_id)} for r in old_rows
    ]

    for r in old_rows:
        db.delete(r)
    db.flush()

    for scope_type, scope_id in validated:
        db.add(
            UserScope(
                user_id=current.id,
                scope_type=scope_type,
                scope_id=scope_id,
            )
        )
    db.flush()

    new_rows = db.scalars(
        select(UserScope)
        .where(UserScope.user_id == current.id)
        .order_by(UserScope.scope_type.asc(), UserScope.scope_id.asc())
    ).all()
    new_snapshot = [
        {"scope_type": r.scope_type, "scope_id": str(r.scope_id)} for r in new_rows
    ]

    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="user_scope",
            entity_id=str(current.id),
            action="user.scopes.replace",
            old_value=redact_for_audit(old_snapshot),
            new_value=redact_for_audit(new_snapshot),
        )
    )
    db.commit()

    final_rows = db.scalars(
        select(UserScope)
        .where(UserScope.user_id == current.id)
        .order_by(UserScope.scope_type.asc(), UserScope.scope_id.asc())
    ).all()
    return ScopeListOut(
        items=[
            ScopeOut(id=r.id, scope_type=r.scope_type, scope_id=r.scope_id)
            for r in final_rows
        ]
    )

# END OF FILE