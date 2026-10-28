"""Employee import: parser and header validation (1C.11).

This file has three parts written across three scripts:
  1. (this script) header validation, CSV row iterator, type parsers.
  2. row validator, opening-rate builder.
  3. the HTTP endpoint itself (dry run + token-gated apply).

The parser is deliberately thin. It does not know about model columns or
types. Its only job is to produce row dicts with string values and drop
blank cells (which is how "blank means leave unchanged" is implemented
for updates). Business-rule and type validation happen in _validate_row.

File format (D1, A):
  - UTF-8, comma-separated, first row is headers.
  - A UTF-8 BOM on the header line is tolerated (utf-8-sig).
  - A row is skipped only when every cell is blank.
  - Columns are matched case-insensitively after trimming.

Caps (D6):
  - file bytes <= 5 MB
  - data rows  <= 5,000
  - error report capped at 500 entries
Anything over the caps is a header-level error and nothing is processed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import select, update

from app.api.deps import TenantDbDep, TenantDep
from app.api.v1.employees_schemas import EmployeeCreateIn, EmployeePatchIn
from app.api.v1.import_schemas import ImportErrorOut, ImportResultOut, OpeningRateOut
from app.core.crypto import TenantCrypto
from app.core.errors import AppError
from app.core.permissions import Permission, check_permission, require_permission
from app.core.scope import ScopeViolation, assert_in_scope
from app.db.tenant.models.organisation import Branch, Department, Site
from app.db.tenant.models.people import Employee, EmployeePayHistory
from app.db.tenant.models.platform import AuditLog
from app.services.audit_redact import redact_for_audit


_MAX_ROWS = 5000
_MAX_BYTES = 5 * 1024 * 1024
_MAX_ERRORS = 500

# Columns that may appear in the header. `effective_from` is not a column
# on Employee; it is only meaningful when `base_rate` is present (D7
# override, opening rate on create). It is in the set so header validation
# does not reject files that carry it.
_ALLOWED_COLUMNS: frozenset[str] = frozenset({
    "employee_code",
    "first_name",
    "last_name",
    "national_id",
    "email",
    "mobile",
    "date_of_birth",
    "hire_date",
    "termination_date",
    "status",
    "job_title",
    "branch_id",
    "site_id",
    "department_id",
    "manager_id",
    "employee_type",
    "pay_basis",
    "pay_frequency",
    "base_rate",
    "overtime_eligible",
    "clocks",
    "work_pattern_id",
    "default_shift_id",
    "bank_name",
    "bank_account_number",
    "bank_branch_code",
    "account_type",
    "tax_number",
    "medical_aid_dependants",
    "retirement_fund_flags",
    "uif_exempt",
    "notes",
    "effective_from",
})

_REQUIRED_ON_CREATE: frozenset[str] = frozenset({
    "employee_code",
    "first_name",
    "last_name",
    "hire_date",
})

_REQUIRED_ON_UPDATE: frozenset[str] = frozenset({"employee_code"})


class _HeaderError(Exception):
    """A header-level error that stops the whole import.

    `column` is the offending column name (or None when the error is about
    the file as a whole: too large, binary content, empty file).
    """

    def __init__(self, column: str | None, code: str, message: str) -> None:
        self.column = column
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class _ParsedRow:
    """One data row after CSV parsing.

    `cells` holds only non-blank values. `structure_error` is set when the
    row has the wrong number of cells; in that case `cells` is empty and the
    row is reported as a single error and skipped.
    """

    number: int  # 1-based data row (first row after the header is 1)
    cells: dict[str, str]
    structure_error: str | None = None


def _open_csv(raw: bytes) -> tuple["_csv._reader", list[str]]:
    """Return (reader positioned after the header, normalised header).

    Raises _HeaderError for any failure that makes the whole file unusable:
    oversize, binary content, non-UTF-8, empty, unknown column, duplicate
    column. The reader is positioned on the first data row.
    """
    if len(raw) == 0:
        raise _HeaderError(None, "empty_file", "File is empty")
    if len(raw) > _MAX_BYTES:
        raise _HeaderError(
            None,
            "file_too_large",
            f"File is {len(raw)} bytes; maximum is {_MAX_BYTES}",
        )
    # Content sniff: any NUL in the first 1 KB means this is not a text CSV
    # (most often an XLSX or XLS saved with a .csv extension).
    if b"\x00" in raw[:1024]:
        raise _HeaderError(
            None,
            "invalid_file_type",
            "File appears to be binary; export the spreadsheet to CSV first",
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _HeaderError(
            None,
            "invalid_encoding",
            f"File is not valid UTF-8: {exc.reason} at byte {exc.start}",
        ) from None

    reader = csv.reader(io.StringIO(text))
    try:
        raw_header = next(reader)
    except StopIteration:
        raise _HeaderError(None, "empty_file", "File has no header row") from None

    header = [h.strip().lower() for h in raw_header]
    if not any(header):
        raise _HeaderError(None, "empty_header", "Header row is empty")

    seen: set[str] = set()
    for h in header:
        if not h:
            continue
        if h not in _ALLOWED_COLUMNS:
            raise _HeaderError(h, "unknown_column", f"Unknown column: {h}")
        if h in seen:
            raise _HeaderError(
                h, "duplicate_column", f"Duplicate column: {h}"
            )
        seen.add(h)

    return reader, header


def _iter_data_rows(
    reader: "_csv._reader", header: list[str]
) -> Iterator[_ParsedRow]:
    """Yield data rows from the reader.

    Fully blank rows are skipped (they are not counted toward _MAX_ROWS).
    A row whose cell count does not match the header is yielded with
    `structure_error` set and empty `cells`. Anything after _MAX_ROWS
    non-blank data rows raises _HeaderError so the endpoint can return
    a clean "file too long" error rather than partially importing.
    """
    data_index = 0
    for raw_row in reader:
        if not any(cell.strip() for cell in raw_row):
            continue
        data_index += 1
        if data_index > _MAX_ROWS:
            raise _HeaderError(
                None,
                "too_many_rows",
                f"File has more than {_MAX_ROWS} data rows",
            )
        if len(raw_row) != len(header):
            yield _ParsedRow(
                number=data_index,
                cells={},
                structure_error=(
                    f"Row has {len(raw_row)} cells; header has {len(header)}"
                ),
            )
            continue
        cells: dict[str, str] = {}
        for col, value in zip(header, raw_row):
            if not col:
                continue
            value = value.strip()
            if value:
                cells[col] = value
        yield _ParsedRow(number=data_index, cells=cells)


# ---------------------------------------------------------------------------
# Type parsers. Each raises ValueError on bad input; the caller wraps that
# into a row-level error with a plain-language message.
# ---------------------------------------------------------------------------


def _parse_date(value: str) -> date:
    """Strict ISO date (YYYY-MM-DD)."""
    return date.fromisoformat(value)


def _parse_decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation:
        raise ValueError(f"not a number: {value!r}") from None


def _parse_int(value: str) -> int:
    return int(value)


_TRUE_VALUES = frozenset({"true", "1", "yes", "y", "t"})
_FALSE_VALUES = frozenset({"false", "0", "no", "n", "f"})


def _parse_bool(value: str) -> bool:
    low = value.strip().lower()
    if low in _TRUE_VALUES:
        return True
    if low in _FALSE_VALUES:
        return False
    raise ValueError(f"not a boolean: {value!r}")


# ---------------------------------------------------------------------------
# Row validation and validated-row model.
# ---------------------------------------------------------------------------


@dataclass
class _ValidatedRow:
    """A row that passed all validation, ready to apply.

    `parsed` holds only the Employee columns that will be set. For updates
    it never contains base_rate (D7 override: existing employees' rates are
    not changed by import) and never contains national_id or
    bank_account_number (create-only). For creates it may contain base_rate
    when the row supplies one, together with an opening_rate record.
    """

    row_number: int
    mode: str  # "create" or "update"
    existing: Employee | None
    parsed: dict[str, Any]
    opening_rate: OpeningRateOut | None
    opening_rate_effective_from: date | None


def _validate_row(
    row: _ParsedRow,
    existing_by_code: dict[str, Employee],
    db: Any,
    user: Any,
) -> tuple[_ValidatedRow | None, list[ImportErrorOut]]:
    """Validate one row.

    Returns (validated, errors). Either `validated` is a _ValidatedRow and
    `errors` is empty, or `validated` is None and `errors` lists every
    problem found for this row. Errors from different rows are aggregated by
    the caller.

    Validation happens in this order, so a row whose employee_code is
    missing produces a single clear error rather than a cascade:
      1. structure (cell count)
      2. employee_code present
      3. required fields for the row's mode (create vs update)
      4. create-only fields not present on update rows
      5. Pydantic parsing (type and allowed-value checks per field)
      6. base_rate rules (D7 override)
      7. effective_from for create opening rates
      8. FK existence (branch, site, department, manager)
      9. scope for the target employee (update rows only; create scope is
         checked at apply time after the employee is inserted)
    """
    errors: list[ImportErrorOut] = []

    def add_error(code: str, message: str, column: str | None = None) -> None:
        errors.append(
            ImportErrorOut(row=row.number, column=column, code=code, message=message)
        )

    if row.structure_error is not None:
        add_error("row_structure_invalid", row.structure_error)
        return None, errors

    code_cell = row.cells.get("employee_code")
    if code_cell is None:
        add_error("missing_employee_code", "employee_code is required", column="employee_code")
        return None, errors

    existing = existing_by_code.get(code_cell.lower())
    mode = "update" if existing is not None else "create"

    required = _REQUIRED_ON_UPDATE if mode == "update" else _REQUIRED_ON_CREATE
    for col in required:
        if col not in row.cells:
            add_error(f"missing_{col}", f"{col} is required on {mode}", column=col)
    if errors:
        return None, errors

    if mode == "update":
        for col in ("national_id", "bank_account_number"):
            if col in row.cells:
                add_error(
                    "field_not_updatable_via_import",
                    f"{col} can only be set when the employee is created",
                    column=col,
                )
        if errors:
            return None, errors

    cells_for_pydantic = {k: v for k, v in row.cells.items() if k != "effective_from"}
    try:
        if mode == "create":
            payload = EmployeeCreateIn(**cells_for_pydantic)
        else:
            payload = EmployeePatchIn(row_version=existing.row_version, **cells_for_pydantic)
    except ValidationError as exc:
        for e in exc.errors():
            column = e["loc"][0] if e.get("loc") else None
            add_error("invalid_field_value", e["msg"], column=str(column) if column else None)
        return None, errors

    supplied = payload.model_dump(exclude_unset=True)
    if mode == "update":
        supplied.pop("row_version", None)

    if mode == "update" and existing is not None:
        # Drop fields whose value already equals the existing value.
        # This is what makes a "no-change" update a no-op rather than a
        # pointless UPDATE that bumps row_version and writes an audit row.
        # Decimal("100.0") == Decimal("100.000000") compares equal, which
        # is what we want for a rate that is unchanged at the database level.
        filtered: dict[str, Any] = {}
        for k, v in supplied.items():
            if v == getattr(existing, k, None):
                continue
            filtered[k] = v
        supplied = filtered

    opening_rate: OpeningRateOut | None = None
    opening_rate_effective_from: date | None = None

    if mode == "update" and "base_rate" in supplied:
        new_rate = supplied["base_rate"]
        current_rate = existing.base_rate
        if new_rate is None and current_rate is None:
            rates_equal = True
        elif new_rate is not None and current_rate is not None and new_rate == current_rate:
            rates_equal = True
        else:
            rates_equal = False
        if not rates_equal:
            add_error(
                "rate_change_requires_approval",
                f"base_rate differs from current ({current_rate}); use the pay-rate approval flow",
                column="base_rate",
            )
        supplied.pop("base_rate", None)

    if mode == "create" and "base_rate" in supplied and supplied["base_rate"] is not None:
        eff_from_cell = row.cells.get("effective_from")
        if not eff_from_cell:
            add_error(
                "opening_rate_effective_from_required",
                "effective_from is required when base_rate is provided on a new employee",
                column="effective_from",
            )
            return None, errors
        try:
            eff_from = _parse_date(eff_from_cell)
        except ValueError:
            add_error(
                "invalid_effective_date",
                f"effective_from is not a valid date (use YYYY-MM-DD): {eff_from_cell}",
                column="effective_from",
            )
            return None, errors
        hire_date = supplied.get("hire_date")
        if hire_date is not None and eff_from < hire_date:
            add_error(
                "invalid_effective_date",
                f"effective_from {eff_from} is before hire_date {hire_date}",
                column="effective_from",
            )
            return None, errors
        opening_rate = OpeningRateOut(
            employee_code=code_cell,
            base_rate=supplied["base_rate"],
            effective_from=eff_from,
        )
        opening_rate_effective_from = eff_from

    if "hire_date" in supplied or "termination_date" in supplied:
        eff_hire = supplied.get("hire_date", existing.hire_date if existing else None)
        eff_term = supplied.get(
            "termination_date", existing.termination_date if existing else None
        )
        if eff_term is not None and eff_hire is not None and eff_term < eff_hire:
            add_error(
                "invalid_termination_date",
                f"termination_date {eff_term} is before hire_date {eff_hire}",
                column="termination_date",
            )

    if "branch_id" in supplied and supplied["branch_id"] is not None:
        if db.get(Branch, supplied["branch_id"]) is None:
            add_error(
                "invalid_branch",
                f"branch_id {supplied['branch_id']} does not exist",
                column="branch_id",
            )
    if "site_id" in supplied and supplied["site_id"] is not None:
        if db.get(Site, supplied["site_id"]) is None:
            add_error(
                "invalid_site",
                f"site_id {supplied['site_id']} does not exist",
                column="site_id",
            )
    if "department_id" in supplied and supplied["department_id"] is not None:
        if db.get(Department, supplied["department_id"]) is None:
            add_error(
                "invalid_department",
                f"department_id {supplied['department_id']} does not exist",
                column="department_id",
            )
    if "manager_id" in supplied and supplied["manager_id"] is not None:
        mgr = db.get(Employee, supplied["manager_id"])
        if mgr is None or mgr.status == "terminated":
            add_error(
                "invalid_manager",
                f"manager_id {supplied['manager_id']} does not exist or is terminated",
                column="manager_id",
            )
        else:
            try:
                assert_in_scope(user, supplied["manager_id"], db)
            except ScopeViolation:
                add_error(
                    "invalid_manager",
                    f"manager_id {supplied['manager_id']} is outside your scope",
                    column="manager_id",
                )

    if mode == "update":
        try:
            assert_in_scope(user, existing.id, db)
        except ScopeViolation:
            add_error(
                "out_of_scope",
                f"employee {existing.employee_code} is outside your scope",
            )

    if errors:
        return None, errors

    return _ValidatedRow(
        row_number=row.number,
        mode=mode,
        existing=existing,
        parsed=supplied,
        opening_rate=opening_rate,
        opening_rate_effective_from=opening_rate_effective_from,
    ), []


# ---------------------------------------------------------------------------
# Router, hashing, snapshot helpers, and per-row apply.
# The endpoint itself is added in script 4b of 6.
# ---------------------------------------------------------------------------


router = APIRouter(prefix="/employees", tags=["employees-import"])


def _sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _to_jsonable(d: dict[str, Any]) -> dict[str, Any]:
    """Convert UUID/date/datetime/Decimal to string for audit JSON."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, (uuid.UUID, date, datetime, Decimal)):
            out[k] = str(v)
        else:
            out[k] = v
    return out


def _apply_validated_row(
    *,
    db: Any,
    user: Any,
    crypto: TenantCrypto,
    validated: _ValidatedRow,
) -> tuple[str, Employee | None, EmployeePayHistory | None, dict[str, Any] | None]:
    """Apply one validated row inside the caller's transaction.

    Returns (mode, employee, opening_rate_row, old_snapshot).
      mode              - "create" or "update"
      employee          - the created or updated Employee (in memory)
      opening_rate_row  - the EmployeePayHistory created for a new
                          employee that supplied base_rate, else None
      old_snapshot      - for updates, dict of the previous values of the
                          fields being changed (JSON-ifiable); None for
                          creates and for no-field updates

    For create mode the caller must treat a ScopeViolation from
    assert_in_scope as a batch-level failure (nothing commits).
    """
    now = datetime.now(timezone.utc)
    parsed = dict(validated.parsed)

    if validated.mode == "create":
        national_plain = parsed.pop("national_id", None)
        bank_plain = parsed.pop("bank_account_number", None)
        opening_rate_value = parsed.pop("base_rate", None)

        employee = Employee(
            **parsed,
            national_id_encrypted=(
                crypto.encrypt(national_plain) if national_plain else None
            ),
            bank_account_number_encrypted=(
                crypto.encrypt(bank_plain) if bank_plain else None
            ),
            row_version=1,
        )
        db.add(employee)
        db.flush()

        opening_rate_row: EmployeePayHistory | None = None
        if opening_rate_value is not None and validated.opening_rate_effective_from is not None:
            employee.base_rate = opening_rate_value
            opening_rate_row = EmployeePayHistory(
                employee_id=employee.id,
                base_rate=opening_rate_value,
                effective_from=validated.opening_rate_effective_from,
                changed_by=getattr(user, "id", None),
                approved_by=getattr(user, "id", None),
                decided_by=getattr(user, "id", None),
                decided_at=now,
                source="import",
                status="approved",
            )
            db.add(opening_rate_row)

        try:
            assert_in_scope(user, employee.id, db)
        except ScopeViolation:
            raise AppError(
                "out_of_scope",
                f"employee {employee.employee_code} is outside your scope",
                status.HTTP_409_CONFLICT,
            ) from None

        return "create", employee, opening_rate_row, None

    existing = validated.existing
    assert existing is not None

    if not parsed:
        return "update", existing, None, None

    old_snapshot = _to_jsonable(
        {k: getattr(existing, k, None) for k in parsed.keys()}
    )

    new_version = existing.row_version + 1
    stmt = (
        update(Employee)
        .where(
            Employee.id == existing.id,
            Employee.row_version == existing.row_version,
        )
        .values(**parsed, row_version=new_version)
    )
    result = db.execute(stmt)
    if result.rowcount == 0:
        raise AppError(
            "concurrent_modification",
            f"employee {existing.employee_code} changed since validation; re-run the dry run",
            status.HTTP_409_CONFLICT,
        )
    db.expire(existing)

    return "update", existing, None, old_snapshot


def _audit_row(
    *,
    db: Any,
    user: Any,
    action: str,
    entity_type: str,
    entity_id: str,
    old_value: Any,
    new_value: Any,
) -> None:
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type=entity_type,
            entity_id=str(entity_id),
            action=action,
            old_value=redact_for_audit(old_value),
            new_value=redact_for_audit(new_value),
        )
    )


# ---------------------------------------------------------------------------
# POST /employees/import
#
# Two-call stateless protocol (D3 override):
#   call 1: no `token` form field -> dry run. Validates every row, applies
#           inside the session, then rolls back. Returns the sha256 of the
#           file bytes as the `token`.
#   call 2: with `token=<sha256>` -> real import. Recomputes the sha256 of
#           the uploaded file; a mismatch is 409 file_changed_since_dry_run.
#
# All-or-nothing (D4A): any row error means nothing is applied, and the
# response is 200 with the row-by-row report and counts of zero. A
# batch-level failure (out_of_scope in create path, concurrent_modification
# on update) rolls back and re-raises.
#
# Row error codes surfaced to HR:
#   missing_employee_code, missing_<field>, invalid_field_value,
#   rate_change_requires_approval, opening_rate_effective_from_required,
#   invalid_effective_date, invalid_termination_date, invalid_branch,
#   invalid_site, invalid_department, invalid_manager, out_of_scope,
#   field_not_updatable_via_import, row_structure_invalid.
#
# Header error codes (400):
#   empty_file, file_too_large, invalid_file_type, invalid_encoding,
#   empty_header, unknown_column, duplicate_column, too_many_rows.
# ---------------------------------------------------------------------------


@router.post("/import", response_model=ImportResultOut)
def import_employees(
    db: TenantDbDep,
    tenant: TenantDep,
    user: Annotated[Any, Depends(require_permission(Permission.EMPLOYEE_CRUD))],
    file: Annotated[UploadFile, File(...)],
    token: Annotated[str | None, Form()] = None,
) -> ImportResultOut:
    raw = file.file.read()
    sha256 = _sha256_hex(raw)

    if token is not None and token != sha256:
        raise AppError(
            "file_changed_since_dry_run",
            "Uploaded file does not match the one that was dry-run; re-run the dry run",
            status.HTTP_409_CONFLICT,
        )

    is_dry_run = token is None

    try:
        reader, header = _open_csv(raw)
    except _HeaderError as exc:
        raise AppError(exc.code, exc.message, status.HTTP_400_BAD_REQUEST) from None

    existing_by_code: dict[str, Employee] = {
        emp.employee_code.lower(): emp
        for emp in db.scalars(select(Employee)).all()
    }

    validated: list[_ValidatedRow] = []
    errors: list[ImportErrorOut] = []
    total_rows = 0

    try:
        for parsed_row in _iter_data_rows(reader, header):
            total_rows += 1
            validated_row, row_errors = _validate_row(
                parsed_row, existing_by_code, db, user
            )
            if validated_row is not None:
                validated.append(validated_row)
            errors.extend(row_errors)
    except _HeaderError as exc:
        raise AppError(exc.code, exc.message, status.HTTP_400_BAD_REQUEST) from None

    invalid_rows = len({e.row for e in errors})

    requires_admin_review = not check_permission(user, Permission.PAY_RATE_APPROVE)

    if errors:
        return ImportResultOut(
            dry_run=is_dry_run,
            token=sha256,
            total_rows=total_rows,
            valid_rows=len(validated),
            invalid_rows=invalid_rows,
            created=0,
            updated=0,
            opening_rates_loaded=0,
            opening_rates=[],
            opening_rates_require_payroll_admin_review=requires_admin_review,
            errors=errors[:_MAX_ERRORS],
            errors_truncated=len(errors) > _MAX_ERRORS,
        )

    crypto = tenant.crypto
    created = 0
    updated = 0
    opening_rates: list[OpeningRateOut] = []

    try:
        for v in validated:
            mode, employee, opening_rate_row, old_snapshot = _apply_validated_row(
                db=db, user=user, crypto=crypto, validated=v
            )
            if mode == "create":
                created += 1
                if opening_rate_row is not None:
                    opening_rates.append(v.opening_rate)  # type: ignore[arg-type]
                    _audit_row(
                        db=db, user=user,
                        action="pay_history.import",
                        entity_type="employee_pay_history",
                        entity_id=str(opening_rate_row.id),
                        old_value=None,
                        new_value={
                            "employee_code": employee.employee_code,
                            "base_rate": str(opening_rate_row.base_rate),
                            "effective_from": opening_rate_row.effective_from.isoformat(),
                            "source": "import",
                        },
                    )
                _audit_row(
                    db=db, user=user,
                    action="employee.import",
                    entity_type="employee",
                    entity_id=str(employee.id),
                    old_value=None,
                    new_value=_to_jsonable(v.parsed),
                )
            else:
                if old_snapshot is not None:
                    updated += 1
                    _audit_row(
                        db=db, user=user,
                        action="employee.import_update",
                        entity_type="employee",
                        entity_id=str(employee.id),
                        old_value=old_snapshot,
                        new_value=_to_jsonable(v.parsed),
                    )

        _audit_row(
            db=db, user=user,
            action="employee_import.apply",
            entity_type="employee_import",
            entity_id=str(uuid.uuid4()),
            old_value=None,
            new_value={
                "filename": file.filename or "",
                "sha256": sha256,
                "total_rows": total_rows,
                "created": created,
                "updated": updated,
                "opening_rates_loaded": len(opening_rates),
            },
        )
    except AppError:
        db.rollback()
        raise

    if is_dry_run:
        db.rollback()
    else:
        db.commit()

    return ImportResultOut(
        dry_run=is_dry_run,
        token=sha256,
        total_rows=total_rows,
        valid_rows=len(validated),
        invalid_rows=total_rows - len(validated),
        created=created,
        updated=updated,
        opening_rates_loaded=len(opening_rates),
        opening_rates=opening_rates,
        opening_rates_require_payroll_admin_review=requires_admin_review,
        errors=[],
        errors_truncated=False,
    )

# END OF FILE