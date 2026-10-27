"""Employee CRUD, list, self-service read (1C.8).

Every endpoint is tenant-scoped (TenantDbDep), permission-checked:
  - EMPLOYEE_CRUD (hr, payroll_admin) for list, read-by-id, create, patch.
  - SELF_VIEW for GET /me.
  - DELETE returns 405 method_not_allowed: employees are never hard-deleted;
    terminate via PATCH status="terminated".

Encryption: TenantCrypto is carried on TenantContext (TenantDep) and passed
to each endpoint explicitly. national_id and bank_account_number are
accepted on create only, encrypted with TenantCrypto before insert, masked
on read (***<last4> / ****<last4>), and returned in full only by
GET /employees/me. PATCH refuses both with 400 field_not_patchable.

Scope: list uses apply_scope(select(Employee), user, db). Single-row reads
and writes use assert_in_scope(user, employee_id, db). GET /me skips the
scope check because it is the caller's own row. Out-of-scope returns 404
record_not_found, not 403, so an out-of-scope record is indistinguishable
from a missing one (IDOR mitigation).
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select, update

from app.api.deps import TenantDbDep, TenantDep
from app.api.v1.employees_schemas import (
    PATCH_FORBIDDEN_FIELDS,
    EmployeeCreateIn,
    EmployeeListOut,
    EmployeeMeOut,
    EmployeeOut,
    EmployeePatchIn,
)
from app.core.crypto import TenantCrypto
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, apply_scope, assert_in_scope
from app.db.tenant.models.organisation import Branch, Department, Site
from app.db.tenant.models.people import Employee
from app.db.tenant.models.platform import AuditLog
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix="/employees", tags=["employees"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _not_found() -> AppError:
    return AppError("record_not_found", "Employee not found", status.HTTP_404_NOT_FOUND)


def _mask_national_id(plain: str | None) -> str | None:
    if not plain:
        return None
    tail = plain[-4:] if len(plain) >= 4 else plain
    return f"***{tail}"


def _mask_bank_account_number(plain: str | None) -> str | None:
    if not plain:
        return None
    tail = plain[-4:] if len(plain) >= 4 else plain
    return f"****{tail}"


def _to_out(employee: Employee, *, crypto: TenantCrypto, decrypt: bool) -> EmployeeOut:
    national_plain = None
    bank_plain = None
    if decrypt:
        if employee.national_id_encrypted:
            national_plain = crypto.decrypt(employee.national_id_encrypted)
        if employee.bank_account_number_encrypted:
            bank_plain = crypto.decrypt(employee.bank_account_number_encrypted)

    national_masked = _mask_national_id(national_plain) if national_plain else None
    bank_masked = _mask_bank_account_number(bank_plain) if bank_plain else None

    return EmployeeOut(
        id=employee.id,
        employee_code=employee.employee_code,
        first_name=employee.first_name,
        last_name=employee.last_name,
        national_id_masked=national_masked,
        email=employee.email,
        mobile=employee.mobile,
        date_of_birth=employee.date_of_birth,
        hire_date=employee.hire_date,
        termination_date=employee.termination_date,
        status=employee.status,
        job_title=employee.job_title,
        branch_id=employee.branch_id,
        site_id=employee.site_id,
        department_id=employee.department_id,
        manager_id=employee.manager_id,
        employee_type=employee.employee_type,
        pay_basis=employee.pay_basis,
        pay_frequency=employee.pay_frequency,
        base_rate=employee.base_rate,
        overtime_eligible=employee.overtime_eligible,
        clocks=employee.clocks,
        work_pattern_id=employee.work_pattern_id,
        default_shift_id=employee.default_shift_id,
        bank_name=employee.bank_name,
        bank_account_number_masked=bank_masked,
        bank_branch_code=employee.bank_branch_code,
        account_type=employee.account_type,
        tax_number=employee.tax_number,
        medical_aid_dependants=employee.medical_aid_dependants,
        retirement_fund_flags=employee.retirement_fund_flags,
        uif_exempt=employee.uif_exempt,
        notes=employee.notes,
        row_version=employee.row_version,
    )


def _to_me(employee: Employee, *, crypto: TenantCrypto) -> EmployeeMeOut:
    national_plain = None
    bank_plain = None
    if employee.national_id_encrypted:
        national_plain = crypto.decrypt(employee.national_id_encrypted)
    if employee.bank_account_number_encrypted:
        bank_plain = crypto.decrypt(employee.bank_account_number_encrypted)

    return EmployeeMeOut(
        id=employee.id,
        employee_code=employee.employee_code,
        first_name=employee.first_name,
        last_name=employee.last_name,
        national_id_masked=_mask_national_id(national_plain),
        email=employee.email,
        mobile=employee.mobile,
        date_of_birth=employee.date_of_birth,
        hire_date=employee.hire_date,
        termination_date=employee.termination_date,
        status=employee.status,
        job_title=employee.job_title,
        branch_id=employee.branch_id,
        site_id=employee.site_id,
        department_id=employee.department_id,
        manager_id=employee.manager_id,
        employee_type=employee.employee_type,
        pay_basis=employee.pay_basis,
        pay_frequency=employee.pay_frequency,
        base_rate=employee.base_rate,
        overtime_eligible=employee.overtime_eligible,
        clocks=employee.clocks,
        work_pattern_id=employee.work_pattern_id,
        default_shift_id=employee.default_shift_id,
        bank_name=employee.bank_name,
        bank_account_number_masked=_mask_bank_account_number(bank_plain),
        bank_branch_code=employee.bank_branch_code,
        account_type=employee.account_type,
        tax_number=employee.tax_number,
        medical_aid_dependants=employee.medical_aid_dependants,
        retirement_fund_flags=employee.retirement_fund_flags,
        uif_exempt=employee.uif_exempt,
        notes=employee.notes,
        row_version=employee.row_version,
        national_id=national_plain,
        bank_account_number=bank_plain,
    )


def _encode_cursor(created_at: datetime, employee_id: uuid.UUID) -> str:
    payload = {"c": created_at.isoformat(), "i": str(employee_id)}
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
        employee_id = uuid.UUID(payload["i"])
        return created_at, employee_id
    except Exception:
        raise AppError(
            "invalid_cursor",
            "The pagination cursor is malformed",
            status.HTTP_400_BAD_REQUEST,
        ) from None


def _validate_branch(db: Any, branch_id: uuid.UUID) -> Branch:
    b = db.get(Branch, branch_id)
    if b is None or not b.is_active:
        raise AppError(
            "invalid_branch",
            f"Branch {branch_id} does not exist or is inactive",
            status.HTTP_400_BAD_REQUEST,
            {"branch_id": str(branch_id)},
        )
    return b


def _validate_site(db: Any, site_id: uuid.UUID) -> Site:
    s = db.get(Site, site_id)
    if s is None or not s.is_active:
        raise AppError(
            "invalid_site",
            f"Site {site_id} does not exist or is inactive",
            status.HTTP_400_BAD_REQUEST,
            {"site_id": str(site_id)},
        )
    return s


def _validate_department(db: Any, department_id: uuid.UUID) -> Department:
    d = db.get(Department, department_id)
    if d is None or not d.is_active:
        raise AppError(
            "invalid_department",
            f"Department {department_id} does not exist or is inactive",
            status.HTTP_400_BAD_REQUEST,
            {"department_id": str(department_id)},
        )
    return d


def _validate_manager(
    db: Any, user: Any, manager_id: uuid.UUID, *, self_id: uuid.UUID | None
) -> Employee:
    if self_id is not None and manager_id == self_id:
        raise AppError(
            "invalid_manager",
            "An employee cannot be their own manager",
            status.HTTP_400_BAD_REQUEST,
            {"manager_id": str(manager_id)},
        )
    m = db.get(Employee, manager_id)
    if m is None or m.status == "terminated":
        raise AppError(
            "invalid_manager",
            f"Manager {manager_id} does not exist or is terminated",
            status.HTTP_400_BAD_REQUEST,
            {"manager_id": str(manager_id)},
        )
    try:
        assert_in_scope(user, manager_id, db)
    except ScopeViolation:
        raise AppError(
            "invalid_manager",
            f"Manager {manager_id} is outside the current user's scope",
            status.HTTP_400_BAD_REQUEST,
            {"manager_id": str(manager_id)},
        ) from None
    return m


def _validate_termination_date(hire_date, termination_date) -> None:
    if termination_date is not None and hire_date is not None:
        if termination_date < hire_date:
            raise AppError(
                "invalid_termination_date",
                "termination_date must not be before hire_date",
                status.HTTP_400_BAD_REQUEST,
            )


@router.get("", response_model=EmployeeListOut)
def list_employees(
    db: TenantDbDep,
    tenant: TenantDep,
    user: Annotated[Any, Depends(require_permission(Permission.EMPLOYEE_CRUD))],
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
    include_total: bool = Query(False),
    include_terminated: bool = Query(False),
    employee_code: str | None = Query(None),
    last_name: str | None = Query(None),
    branch_id: uuid.UUID | None = Query(None),
    site_id: uuid.UUID | None = Query(None),
    department_id: uuid.UUID | None = Query(None),
    manager_id: uuid.UUID | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    employee_type: str | None = Query(None),
    is_manager: bool | None = Query(None),
) -> EmployeeListOut:
    crypto = tenant.crypto

    q = select(Employee)
    if not include_terminated:
        q = q.where(Employee.status != "terminated")
    if employee_code is not None:
        q = q.where(
            func.lower(Employee.employee_code) == employee_code.strip().lower()
        )
    if last_name is not None:
        q = q.where(
            func.lower(Employee.last_name).like(f"%{last_name.strip().lower()}%")
        )
    if branch_id is not None:
        q = q.where(Employee.branch_id == branch_id)
    if site_id is not None:
        q = q.where(Employee.site_id == site_id)
    if department_id is not None:
        q = q.where(Employee.department_id == department_id)
    if manager_id is not None:
        q = q.where(Employee.manager_id == manager_id)
    if status_filter is not None:
        q = q.where(Employee.status == status_filter)
    if employee_type is not None:
        q = q.where(Employee.employee_type == employee_type)
    if is_manager is not None:
        sub = (
            select(Employee.manager_id)
            .where(Employee.manager_id.is_not(None))
            .distinct()
        )
        if is_manager:
            q = q.where(Employee.id.in_(sub))
        else:
            q = q.where(~Employee.id.in_(sub))

    q = apply_scope(q, user, db)

    if cursor is not None:
        cursor_ts, cursor_id = _decode_cursor(cursor)
        q = q.where(
            or_(
                Employee.created_at > cursor_ts,
                (Employee.created_at == cursor_ts) & (Employee.id > cursor_id),
            )
        )

    q = q.order_by(Employee.created_at.asc(), Employee.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    total: int | None = None
    if include_total:
        tq = select(func.count()).select_from(Employee)
        if not include_terminated:
            tq = tq.where(Employee.status != "terminated")
        if employee_code is not None:
            tq = tq.where(
                func.lower(Employee.employee_code) == employee_code.strip().lower()
            )
        if last_name is not None:
            tq = tq.where(
                func.lower(Employee.last_name).like(f"%{last_name.strip().lower()}%")
            )
        if branch_id is not None:
            tq = tq.where(Employee.branch_id == branch_id)
        if site_id is not None:
            tq = tq.where(Employee.site_id == site_id)
        if department_id is not None:
            tq = tq.where(Employee.department_id == department_id)
        if manager_id is not None:
            tq = tq.where(Employee.manager_id == manager_id)
        if status_filter is not None:
            tq = tq.where(Employee.status == status_filter)
        if employee_type is not None:
            tq = tq.where(Employee.employee_type == employee_type)
        if is_manager is not None:
            sub = (
                select(Employee.manager_id)
                .where(Employee.manager_id.is_not(None))
                .distinct()
            )
            if is_manager:
                tq = tq.where(Employee.id.in_(sub))
            else:
                tq = tq.where(~Employee.id.in_(sub))
        tq = apply_scope(tq, user, db)
        total = int(db.scalar(tq) or 0)

    return EmployeeListOut(
        items=[_to_out(r, crypto=crypto, decrypt=True) for r in rows],
        next_cursor=next_cursor,
        total=total,
    )


@router.get("/me", response_model=EmployeeMeOut)
def get_me(
    db: TenantDbDep,
    tenant: TenantDep,
    user: Annotated[Any, Depends(require_permission(Permission.SELF_VIEW))],
) -> EmployeeMeOut:
    crypto = tenant.crypto
    employee_id = getattr(user, "employee_id", None)
    if employee_id is None:
        raise AppError(
            "no_employee_record",
            "This user has no employee record",
            status.HTTP_404_NOT_FOUND,
        )
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise AppError(
            "no_employee_record",
            "This user has no employee record",
            status.HTTP_404_NOT_FOUND,
        )
    return _to_me(employee, crypto=crypto)


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeeCreateIn,
    db: TenantDbDep,
    tenant: TenantDep,
    user: Annotated[Any, Depends(require_permission(Permission.EMPLOYEE_CRUD))],
) -> EmployeeOut:
    crypto = tenant.crypto

    if payload.branch_id is not None:
        _validate_branch(db, payload.branch_id)
    if payload.site_id is not None:
        _validate_site(db, payload.site_id)
    if payload.department_id is not None:
        _validate_department(db, payload.department_id)
    if payload.manager_id is not None:
        _validate_manager(db, user, payload.manager_id, self_id=None)
    _validate_termination_date(payload.hire_date, payload.termination_date)

    clean_code = payload.employee_code.strip()
    existing = db.scalar(
        select(Employee).where(
            func.lower(Employee.employee_code) == clean_code.lower()
        )
    )
    if existing is not None:
        raise AppError(
            "duplicate_code",
            f"An employee with code '{clean_code}' already exists",
            status.HTTP_409_CONFLICT,
        )

    encrypted_national_id = (
        crypto.encrypt(payload.national_id) if payload.national_id else None
    )
    encrypted_bank_account = (
        crypto.encrypt(payload.bank_account_number)
        if payload.bank_account_number
        else None
    )

    employee = Employee(
        employee_code=clean_code,
        first_name=payload.first_name,
        last_name=payload.last_name,
        national_id_encrypted=encrypted_national_id,
        email=payload.email,
        mobile=payload.mobile,
        date_of_birth=payload.date_of_birth,
        hire_date=payload.hire_date,
        termination_date=payload.termination_date,
        status=payload.status,
        job_title=payload.job_title,
        branch_id=payload.branch_id,
        site_id=payload.site_id,
        department_id=payload.department_id,
        manager_id=payload.manager_id,
        employee_type=payload.employee_type,
        pay_basis=payload.pay_basis,
        pay_frequency=payload.pay_frequency,
        base_rate=payload.base_rate,
        overtime_eligible=payload.overtime_eligible,
        clocks=payload.clocks,
        work_pattern_id=payload.work_pattern_id,
        default_shift_id=payload.default_shift_id,
        bank_name=payload.bank_name,
        bank_account_number_encrypted=encrypted_bank_account,
        bank_branch_code=payload.bank_branch_code,
        account_type=payload.account_type,
        tax_number=payload.tax_number,
        medical_aid_dependants=payload.medical_aid_dependants,
        retirement_fund_flags=payload.retirement_fund_flags,
        uif_exempt=payload.uif_exempt,
        notes=payload.notes,
        row_version=1,
    )
    db.add(employee)
    db.flush()

    new_snapshot = _to_out(employee, crypto=crypto, decrypt=False).model_dump(mode="json")
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="employee",
            entity_id=str(employee.id),
            action="employee.create",
            old_value=None,
            new_value=redact_for_audit(new_snapshot),
        )
    )
    db.commit()
    db.refresh(employee)
    return _to_out(employee, crypto=crypto, decrypt=True)


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(
    employee_id: uuid.UUID,
    db: TenantDbDep,
    tenant: TenantDep,
    user: Annotated[Any, Depends(require_permission(Permission.EMPLOYEE_CRUD))],
) -> EmployeeOut:
    crypto = tenant.crypto
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise _not_found() from None
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise _not_found()
    return _to_out(employee, crypto=crypto, decrypt=True)


@router.patch("/{employee_id}", response_model=EmployeeOut)
def patch_employee(
    employee_id: uuid.UUID,
    payload: EmployeePatchIn,
    db: TenantDbDep,
    tenant: TenantDep,
    user: Annotated[Any, Depends(require_permission(Permission.EMPLOYEE_CRUD))],
) -> EmployeeOut:
    crypto = tenant.crypto
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise _not_found() from None

    current = db.get(Employee, employee_id)
    if current is None:
        raise _not_found()

    if current.row_version != payload.row_version:
        raise AppError(
            "record_changed",
            f"Employee has changed (current version {current.row_version}); "
            "reload and retry",
            status.HTTP_409_CONFLICT,
            {"current_row_version": current.row_version},
        )

    supplied = payload.model_dump(exclude_unset=True)
    forbidden = PATCH_FORBIDDEN_FIELDS & set(supplied.keys())
    if forbidden:
        raise AppError(
            "field_not_patchable",
            f"The following fields cannot be changed via PATCH: "
            f"{', '.join(sorted(forbidden))}",
            status.HTTP_400_BAD_REQUEST,
            {"fields": sorted(forbidden)},
        )

    update_fields: dict[str, Any] = {}

    if "employee_code" in supplied and supplied["employee_code"] is not None:
        clean_code = supplied["employee_code"].strip()
        clash = db.scalar(
            select(Employee).where(
                func.lower(Employee.employee_code) == clean_code.lower(),
                Employee.id != current.id,
            )
        )
        if clash is not None:
            raise AppError(
                "duplicate_code",
                f"An employee with code '{clean_code}' already exists",
                status.HTTP_409_CONFLICT,
            )
        update_fields["employee_code"] = clean_code

    if "branch_id" in supplied:
        if supplied["branch_id"] is None:
            update_fields["branch_id"] = None
        else:
            _validate_branch(db, supplied["branch_id"])
            update_fields["branch_id"] = supplied["branch_id"]

    if "site_id" in supplied:
        if supplied["site_id"] is None:
            update_fields["site_id"] = None
        else:
            _validate_site(db, supplied["site_id"])
            update_fields["site_id"] = supplied["site_id"]

    if "department_id" in supplied:
        if supplied["department_id"] is None:
            update_fields["department_id"] = None
        else:
            _validate_department(db, supplied["department_id"])
            update_fields["department_id"] = supplied["department_id"]

    if "manager_id" in supplied:
        if supplied["manager_id"] is None:
            update_fields["manager_id"] = None
        else:
            _validate_manager(
                db, user, supplied["manager_id"], self_id=current.id
            )
            update_fields["manager_id"] = supplied["manager_id"]

    prospective_hire_date = supplied.get("hire_date", current.hire_date)
    prospective_termination = supplied.get(
        "termination_date", current.termination_date
    )
    _validate_termination_date(prospective_hire_date, prospective_termination)

    for simple_key in (
        "first_name", "last_name", "email", "mobile", "date_of_birth",
        "hire_date", "termination_date", "status", "job_title",
        "employee_type", "pay_basis", "pay_frequency", "base_rate",
        "overtime_eligible", "clocks", "work_pattern_id", "default_shift_id",
        "bank_name", "bank_branch_code", "account_type", "tax_number",
        "medical_aid_dependants", "retirement_fund_flags", "uif_exempt", "notes",
    ):
        if simple_key in supplied:
            update_fields[simple_key] = supplied[simple_key]

    if not update_fields:
        return _to_out(current, crypto=crypto, decrypt=True)

    old_snapshot = _to_out(current, crypto=crypto, decrypt=False).model_dump(mode="json")
    new_version = current.row_version + 1

    stmt = (
        update(Employee)
        .where(
            Employee.id == current.id,
            Employee.row_version == payload.row_version,
        )
        .values(**update_fields, row_version=new_version)
    )
    result = db.execute(stmt)
    if result.rowcount == 0:
        db.rollback()
        raise AppError(
            "record_changed",
            "Employee changed during this request; reload and retry",
            status.HTTP_409_CONFLICT,
        )

    db.expire_all()
    db.flush()
    refreshed = db.scalar(select(Employee).where(Employee.id == current.id))
    assert refreshed is not None
    new_snapshot = _to_out(refreshed, crypto=crypto, decrypt=False).model_dump(mode="json")

    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="employee",
            entity_id=str(current.id),
            action="employee.update",
            old_value=redact_for_audit(old_snapshot),
            new_value=redact_for_audit(new_snapshot),
        )
    )
    db.commit()
    db.refresh(refreshed)
    return _to_out(refreshed, crypto=crypto, decrypt=True)


@router.delete(
    "/{employee_id}",
    status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
    response_class=Response,
    response_model=None,
)
def delete_employee(
    employee_id: uuid.UUID,
    tenant: TenantDep,
    user: Annotated[Any, Depends(require_permission(Permission.EMPLOYEE_CRUD))],
) -> Response:
    raise AppError(
        "method_not_allowed",
        "Employees cannot be deleted; terminate via PATCH status='terminated'",
        status.HTTP_405_METHOD_NOT_ALLOWED,
    )

# END OF FILE