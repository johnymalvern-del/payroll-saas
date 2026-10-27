"""Department CRUD, list, deactivate, reactivate, delete (1C.7).

Every endpoint is tenant-scoped (TenantDbDep), permission-checked (ORG_VIEW
for reads, ORG_MANAGE for writes) and scope-checked via
apply_department_scope (list) or assert_department_in_scope (single-row).
Scope violations and missing rows both return 404 record_not_found (IDOR
mitigation).

List envelope is the codebase standard:
    {"items": [...], "next_cursor": "..."}
with ?include_total=true adding "total". Default limit 100, max 500.

Filters: parent_id, is_active.

Error codes:
  duplicate_code                - department code exists (case-insensitive)
  invalid_parent                - parent_id missing, self-referential, or cycle
  department_has_children       - delete refused: children exist
  department_has_active_children - deactivate refused: active children exist
  department_in_use             - delete refused: employees reference it
  record_changed                - row_version mismatch on PATCH
  record_not_found              - department not found, or outside scope

1C.8 must add: PATCH is_active=false must be refused with 409
department_has_active_employees when any active employee still references
the department. The guard is NOT in this file yet; the Employee.department_id
column exists, so the guard can be added later without a schema change.
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
from app.api.v1.departments_schemas import (
    DepartmentCreateIn,
    DepartmentListOut,
    DepartmentOut,
    DepartmentPatchIn,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import (
    ScopeViolation,
    apply_department_scope,
    assert_department_in_scope,
)
from app.db.tenant.models.organisation import Department
from app.db.tenant.models.people import Employee
from app.db.tenant.models.platform import AuditLog
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix="/departments", tags=["departments"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_MAX_ANCESTOR_WALK = 100


def _to_out(d: Department) -> DepartmentOut:
    return DepartmentOut(
        id=d.id,
        name=d.name,
        code=d.code,
        parent_id=d.parent_id,
        is_active=d.is_active,
        row_version=d.row_version,
    )


def _encode_cursor(created_at: datetime, department_id: uuid.UUID) -> str:
    payload = {"c": created_at.isoformat(), "i": str(department_id)}
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
        department_id = uuid.UUID(payload["i"])
        return created_at, department_id
    except Exception:
        raise AppError(
            "invalid_cursor",
            "The pagination cursor is malformed",
            status.HTTP_400_BAD_REQUEST,
        ) from None


def _not_found() -> AppError:
    return AppError(
        "record_not_found", "Department not found", status.HTTP_404_NOT_FOUND
    )


def _would_cycle(db: Any, department_id: uuid.UUID, new_parent_id: uuid.UUID) -> bool:
    """Return True if setting parent=new_parent_id on department_id cycles.

    Walks ancestors from new_parent_id. If any is department_id, the move
    would create a cycle. A depth cap guards against existing bad data and
    against pathological trees.
    """
    current: uuid.UUID | None = new_parent_id
    steps = 0
    while current is not None and steps < _MAX_ANCESTOR_WALK:
        if current == department_id:
            return True
        row = db.scalar(select(Department.parent_id).where(Department.id == current))
        current = row
        steps += 1
    return False


def _validate_parent(
    db: Any, *, department_id: uuid.UUID | None, parent_id: uuid.UUID
) -> Department:
    """Validate a parent for create (department_id=None) or patch.

    Raises AppError invalid_parent if the parent is missing, inactive, self-
    referential, or would create a cycle.
    """
    if department_id is not None and parent_id == department_id:
        raise AppError(
            "invalid_parent",
            "A department cannot be its own parent",
            status.HTTP_400_BAD_REQUEST,
            {"parent_id": str(parent_id)},
        )
    parent = db.get(Department, parent_id)
    if parent is None:
        raise AppError(
            "invalid_parent",
            f"Parent department {parent_id} does not exist",
            status.HTTP_400_BAD_REQUEST,
            {"parent_id": str(parent_id)},
        )
    if not parent.is_active:
        raise AppError(
            "invalid_parent",
            f"Parent department {parent_id} is inactive",
            status.HTTP_400_BAD_REQUEST,
            {"parent_id": str(parent_id)},
        )
    if department_id is not None and _would_cycle(db, department_id, parent_id):
        raise AppError(
            "invalid_parent",
            "Reparenting would create a cycle",
            status.HTTP_400_BAD_REQUEST,
            {"parent_id": str(parent_id)},
        )
    return parent


@router.get("", response_model=DepartmentListOut)
def list_departments(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ORG_VIEW))],
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
    include_inactive: bool = Query(False),
    include_total: bool = Query(False),
    parent_id: uuid.UUID | None = Query(None),
    is_active: bool | None = Query(None),
) -> DepartmentListOut:
    q = select(Department)
    if not include_inactive:
        q = q.where(Department.is_active.is_(True))
    if is_active is not None:
        q = q.where(Department.is_active.is_(is_active))
    if parent_id is not None:
        q = q.where(Department.parent_id == parent_id)

    q = apply_department_scope(q, user, db)

    if cursor is not None:
        cursor_ts, cursor_id = _decode_cursor(cursor)
        q = q.where(
            or_(
                Department.created_at > cursor_ts,
                (Department.created_at == cursor_ts) & (Department.id > cursor_id),
            )
        )

    q = q.order_by(Department.created_at.asc(), Department.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    total: int | None = None
    if include_total:
        tq = select(func.count()).select_from(Department)
        if not include_inactive:
            tq = tq.where(Department.is_active.is_(True))
        if is_active is not None:
            tq = tq.where(Department.is_active.is_(is_active))
        if parent_id is not None:
            tq = tq.where(Department.parent_id == parent_id)
        tq = apply_department_scope(tq, user, db)
        total = int(db.scalar(tq) or 0)

    return DepartmentListOut(
        items=[_to_out(r) for r in rows],
        next_cursor=next_cursor,
        total=total,
    )


@router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(
    payload: DepartmentCreateIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ORG_MANAGE))],
) -> DepartmentOut:
    if payload.parent_id is not None:
        _validate_parent(db, department_id=None, parent_id=payload.parent_id)

    clean_code = payload.code.strip()
    existing = db.scalar(
        select(Department).where(func.lower(Department.code) == clean_code.lower())
    )
    if existing is not None:
        raise AppError(
            "duplicate_code",
            f"A department with code '{clean_code}' already exists",
            status.HTTP_409_CONFLICT,
        )

    department = Department(
        name=payload.name,
        code=clean_code,
        parent_id=payload.parent_id,
        is_active=True,
        row_version=1,
    )
    db.add(department)
    db.flush()

    new_snapshot = _to_out(department).model_dump(mode="json")
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="department",
            entity_id=str(department.id),
            action="department.create",
            old_value=None,
            new_value=redact_for_audit(new_snapshot),
        )
    )
    db.commit()
    db.refresh(department)
    return _to_out(department)


@router.get("/{department_id}", response_model=DepartmentOut)
def get_department(
    department_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ORG_VIEW))],
) -> DepartmentOut:
    try:
        assert_department_in_scope(user, department_id, db)
    except ScopeViolation:
        raise _not_found() from None

    department = db.get(Department, department_id)
    if department is None:
        raise _not_found()
    return _to_out(department)


@router.patch("/{department_id}", response_model=DepartmentOut)
def patch_department(
    department_id: uuid.UUID,
    payload: DepartmentPatchIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ORG_MANAGE))],
) -> DepartmentOut:
    try:
        assert_department_in_scope(user, department_id, db)
    except ScopeViolation:
        raise _not_found() from None

    current = db.get(Department, department_id)
    if current is None:
        raise _not_found()

    if current.row_version != payload.row_version:
        raise AppError(
            "record_changed",
            f"Department has changed (current version {current.row_version}); "
            "reload and retry",
            status.HTTP_409_CONFLICT,
            {"current_row_version": current.row_version},
        )

    supplied = payload.model_dump(exclude_unset=True)
    update_fields: dict[str, Any] = {}

    for key in ("name",):
        if key in supplied and supplied[key] is not None:
            update_fields[key] = supplied[key]

    if "parent_id" in supplied:
        new_parent = supplied["parent_id"]
        if new_parent is None:
            update_fields["parent_id"] = None
        else:
            _validate_parent(db, department_id=current.id, parent_id=new_parent)
            update_fields["parent_id"] = new_parent

    if "code" in supplied and supplied["code"] is not None:
        clean_code = supplied["code"].strip()
        clash = db.scalar(
            select(Department).where(
                func.lower(Department.code) == clean_code.lower(),
                Department.id != current.id,
            )
        )
        if clash is not None:
            raise AppError(
                "duplicate_code",
                f"A department with code '{clean_code}' already exists",
                status.HTTP_409_CONFLICT,
            )
        update_fields["code"] = clean_code

    if "is_active" in supplied and supplied["is_active"] is not None:
        new_active = bool(supplied["is_active"])
        if current.is_active and not new_active:
            active_children = int(
                db.scalar(
                    select(func.count()).select_from(Department).where(
                        Department.parent_id == current.id,
                        Department.is_active.is_(True),
                    )
                )
                or 0
            )
            if active_children > 0:
                raise AppError(
                    "department_has_active_children",
                    f"Cannot deactivate department: {active_children} active "
                    "child department(s) reference it",
                    status.HTTP_409_CONFLICT,
                    {"active_children": active_children},
                )
        if (not current.is_active) and new_active and current.parent_id is not None:
            parent = db.get(Department, current.parent_id)
            if parent is None or not parent.is_active:
                raise AppError(
                    "invalid_parent",
                    "Cannot reactivate department: its parent is inactive",
                    status.HTTP_409_CONFLICT,
                    {"parent_id": str(current.parent_id)},
                )
        update_fields["is_active"] = new_active

    if not update_fields:
        return _to_out(current)

    old_snapshot = _to_out(current).model_dump(mode="json")
    new_version = current.row_version + 1

    stmt = (
        update(Department)
        .where(Department.id == current.id, Department.row_version == payload.row_version)
        .values(**update_fields, row_version=new_version)
    )
    result = db.execute(stmt)
    if result.rowcount == 0:
        db.rollback()
        raise AppError(
            "record_changed",
            "Department changed during this request; reload and retry",
            status.HTTP_409_CONFLICT,
        )

    db.expire_all()
    db.flush()
    refreshed = db.scalar(select(Department).where(Department.id == current.id))
    assert refreshed is not None
    new_snapshot = _to_out(refreshed).model_dump(mode="json")

    if old_snapshot.get("is_active") and not new_snapshot.get("is_active"):
        action = "department.deactivate"
    elif (not old_snapshot.get("is_active")) and new_snapshot.get("is_active"):
        action = "department.reactivate"
    else:
        action = "department.update"

    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="department",
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
    "/{department_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_department(
    department_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ORG_MANAGE))],
) -> Response:
    try:
        assert_department_in_scope(user, department_id, db)
    except ScopeViolation:
        raise _not_found() from None

    department = db.get(Department, department_id)
    if department is None:
        raise _not_found()

    children = int(
        db.scalar(
            select(func.count()).select_from(Department).where(
                Department.parent_id == department.id
            )
        )
        or 0
    )
    if children > 0:
        raise AppError(
            "department_has_children",
            f"Cannot delete department: {children} child department(s) "
            "reference it",
            status.HTTP_409_CONFLICT,
            {"children": children},
        )

    employee_count = int(
        db.scalar(
            select(func.count()).select_from(Employee).where(
                Employee.department_id == department.id
            )
        )
        or 0
    )
    if employee_count > 0:
        raise AppError(
            "department_in_use",
            f"Cannot delete department: {employee_count} employee(s) "
            "reference it",
            status.HTTP_409_CONFLICT,
            {"employees": employee_count},
        )

    old_snapshot = _to_out(department).model_dump(mode="json")
    db.delete(department)
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="department",
            entity_id=str(department.id),
            action="department.delete",
            old_value=redact_for_audit(old_snapshot),
            new_value=None,
        )
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# END OF FILE