"""Salary structure service (Chapter 4, Milestone 3, Stage B).

Versioned salary structures. Every edit produces a new immutable version.
The old version and its components are frozen. Assignments pin to a
specific structure_id (version), so editing a template never touches
existing assignments.

Advisory lock on structure_group_id serialises concurrent creates/edits
of the same group. Key derivation is namespace-prefixed SHA-256,
provably distinct from attendance_engine's (emp_uuid[:4], days-since-epoch)
lock key — different byte prefix means different k1/k2 with overwhelming
probability for any pair of distinct callers.

M3.5 item 3 adds list_current_structures_paginated; the unpaginated
list_current_structures is preserved for callers that don't need pages.
"""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tenant.models.pay import DeductionType, EarningType
from app.db.tenant.models.salary_structure import (
    SalaryStructure,
    SalaryStructureComponent,
)
from app.services.payroll_audit import write_audit


_STRUCT_LOCK_NAMESPACE = b"payroll.salary_structure.v1"


def _structure_lock_key(group_id: uuid.UUID) -> tuple[int, int]:
    """Deterministic (k1, k2) for pg_advisory_xact_lock(int4, int4).

    Namespace-prefixed SHA-256 ensures no predictable relation to
    attendance_engine's (employee_uuid[:4], days) key. Collisions across
    namespaces are cryptographically negligible; within-namespace collision
    only widens serialization, never correctness.
    """
    h = hashlib.sha256(_STRUCT_LOCK_NAMESPACE + group_id.bytes).digest()
    k1 = int.from_bytes(h[:4], "big", signed=False) & 0x7FFFFFFF
    k2 = int.from_bytes(h[4:8], "big", signed=False) & 0x7FFFFFFF
    return k1, k2


def _acquire_group_lock(db: Session, group_id: uuid.UUID) -> None:
    k1, k2 = _structure_lock_key(group_id)
    db.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:k1 AS int), CAST(:k2 AS int))"),
        {"k1": k1, "k2": k2},
    )


def _validate_component(
    db: Session, kind: str, *,
    earning_type_id: uuid.UUID | None,
    deduction_type_id: uuid.UUID | None,
) -> None:
    if kind == "earning":
        if earning_type_id is None:
            raise AppError(
                "invalid_component",
                "earning_type_id is required for kind='earning'",
                422,
            )
        et = db.get(EarningType, earning_type_id)
        if et is None:
            raise AppError("not_found", "Earning type not found", 404)
        if et.is_system:
            raise AppError(
                "system_earning_type_not_allowed_in_structure",
                "System earning types cannot be used in salary structures",
                422,
            )
        if et.code == "BASE_MONTHLY":
            raise AppError(
                "base_monthly_component_not_allowed",
                "BASE_MONTHLY cannot be a structure component; use base_rate",
                422,
            )
        if not et.is_active:
            raise AppError(
                "inactive_earning_type_not_allowed",
                "Inactive earning types cannot be used in salary structures",
                422,
            )
    elif kind == "deduction":
        if deduction_type_id is None:
            raise AppError(
                "invalid_component",
                "deduction_type_id is required for kind='deduction'",
                422,
            )
        dt = db.get(DeductionType, deduction_type_id)
        if dt is None:
            raise AppError("not_found", "Deduction type not found", 404)
        if dt.is_system:
            raise AppError(
                "system_deduction_not_allowed_in_structure",
                "System deduction types cannot be used in salary structures",
                422,
            )
        if not dt.is_active:
            raise AppError(
                "inactive_deduction_type_not_allowed",
                "Inactive deduction types cannot be used in salary structures",
                422,
            )
    else:
        raise AppError("invalid_component", f"Unknown component kind {kind!r}", 422)


def _validate_components(db: Session, components: list[dict]) -> None:
    for c in components:
        kind = c["kind"]
        _validate_component(
            db, kind,
            earning_type_id=c.get("earning_type_id"),
            deduction_type_id=c.get("deduction_type_id"),
        )
        if kind == "earning":
            has_amt = c.get("amount") is not None
            has_rate = c.get("rate") is not None
            if has_amt == has_rate:
                raise AppError(
                    "invalid_component",
                    "Earning component requires exactly one of amount or rate",
                    422,
                )
            if c.get("deduction_type_id") is not None:
                raise AppError(
                    "invalid_component",
                    "deduction_type_id must be None for kind='earning'",
                    422,
                )
        else:
            if c.get("amount") is None:
                raise AppError(
                    "invalid_component",
                    "Deduction component requires amount",
                    422,
                )
            if c.get("rate") is not None:
                raise AppError(
                    "invalid_component",
                    "Deduction component must not set rate",
                    422,
                )
            if c.get("earning_type_id") is not None:
                raise AppError(
                    "invalid_component",
                    "earning_type_id must be None for kind='deduction'",
                    422,
                )


def _insert_components(
    db: Session, structure_id: uuid.UUID, components: list[dict],
) -> None:
    for c in components:
        db.add(SalaryStructureComponent(
            structure_id=structure_id,
            kind=c["kind"],
            earning_type_id=c.get("earning_type_id"),
            deduction_type_id=c.get("deduction_type_id"),
            amount=c.get("amount"),
            rate=c.get("rate"),
        ))


def _copy_components(
    db: Session, *, from_structure_id: uuid.UUID, to_structure_id: uuid.UUID,
) -> None:
    rows = db.scalars(select(SalaryStructureComponent).where(
        SalaryStructureComponent.structure_id == from_structure_id,
    )).all()
    for r in rows:
        db.add(SalaryStructureComponent(
            structure_id=to_structure_id,
            kind=r.kind,
            earning_type_id=r.earning_type_id,
            deduction_type_id=r.deduction_type_id,
            amount=r.amount,
            rate=r.rate,
        ))


def create_structure(
    db: Session, user: Any, *,
    name: str,
    description: str | None,
    pay_basis: str,
    base_rate: Decimal,
    components: list[dict],
) -> SalaryStructure:
    _validate_components(db, components)
    group_id = uuid.uuid4()
    _acquire_group_lock(db, group_id)
    structure = SalaryStructure(
        structure_group_id=group_id,
        version_number=1,
        is_current=True,
        name=name,
        description=description,
        pay_basis=pay_basis,
        base_rate=base_rate,
        is_active=True,
    )
    db.add(structure)
    db.flush()
    _insert_components(db, structure.id, components)
    write_audit(
        db, user,
        entity_type="salary_structure",
        entity_id=structure.id,
        action="salary_structure.create",
        new_value={
            "group_id": str(group_id),
            "version_number": 1,
            "name": name,
            "pay_basis": pay_basis,
            "base_rate": str(base_rate),
        },
    )
    return structure


def edit_structure(
    db: Session, user: Any, group_id: uuid.UUID, *,
    version_number: int,
    row_version: int,
    name: str | None = None,
    description: str | None = None,
    pay_basis: str | None = None,
    base_rate: Decimal | None = None,
    components: list[dict] | None = None,
) -> SalaryStructure:
    """Create a new immutable version of the current structure.

    Concurrency guard: caller must supply both the version_number it
    fetched and that version's row_version. row_version alone is
    insufficient because each new version starts at row_version=1.
    """
    _acquire_group_lock(db, group_id)
    current = db.scalar(select(SalaryStructure).where(
        SalaryStructure.structure_group_id == group_id,
        SalaryStructure.is_current == True,  # noqa: E712
    ))
    if current is None:
        raise AppError("not_found", "Salary structure not found", 404)
    if not current.is_active:
        raise AppError(
            "structure_inactive",
            "Salary structure group is inactive",
            409,
        )
    if current.version_number != version_number:
        raise AppError(
            "record_changed",
            "Salary structure was changed; reload before editing",
            409,
        )
    if current.row_version != row_version:
        raise AppError(
            "record_changed",
            "Salary structure was changed by another user",
            409,
        )
    if components is not None:
        _validate_components(db, components)

    current.is_current = False
    db.flush()

    new_version = SalaryStructure(
        structure_group_id=group_id,
        version_number=current.version_number + 1,
        is_current=True,
        name=name if name is not None else current.name,
        description=description if description is not None else current.description,
        pay_basis=pay_basis if pay_basis is not None else current.pay_basis,
        base_rate=base_rate if base_rate is not None else current.base_rate,
        is_active=True,
    )
    db.add(new_version)
    db.flush()

    if components is None:
        _copy_components(
            db,
            from_structure_id=current.id,
            to_structure_id=new_version.id,
        )
    else:
        _insert_components(db, new_version.id, components)

    write_audit(
        db, user,
        entity_type="salary_structure",
        entity_id=new_version.id,
        action="salary_structure.new_version",
        old_value={"prior_version_number": current.version_number},
        new_value={"version_number": new_version.version_number},
    )
    return new_version


def list_current_structures(db: Session) -> list[SalaryStructure]:
    return list(db.scalars(select(SalaryStructure).where(
        SalaryStructure.is_current == True,  # noqa: E712
    ).order_by(SalaryStructure.name.asc())).all())


def _encode_cursor(uid: uuid.UUID) -> str:
    raw = json.dumps({"i": str(uid)}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> uuid.UUID:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        return uuid.UUID(json.loads(raw)["i"])
    except Exception:
        raise AppError(
            "invalid_cursor", "The pagination cursor is malformed", 400,
        ) from None


def list_current_structures_paginated(
    db: Session,
    *,
    limit: int = 100,
    cursor: str | None = None,
) -> tuple[list[SalaryStructure], str | None]:
    """Cursor-paginated list of current salary structures.

    Ordered by id ASC (stable, cursor-safe). Mirrors the cursor pattern
    used in payroll_change_requests: opaque base64url of {"i": "<uuid>"}.

    Returns (items, next_cursor). next_cursor is None on the last page.
    """
    q = select(SalaryStructure).where(
        SalaryStructure.is_current == True,  # noqa: E712
    )
    if cursor is not None:
        q = q.where(SalaryStructure.id > _decode_cursor(cursor))
    q = q.order_by(SalaryStructure.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_cursor(rows[-1].id)
    return rows, next_cursor


def get_current_structure(
    db: Session, group_id: uuid.UUID,
) -> SalaryStructure:
    s = db.scalar(select(SalaryStructure).where(
        SalaryStructure.structure_group_id == group_id,
        SalaryStructure.is_current == True,  # noqa: E712
    ))
    if s is None:
        raise AppError("not_found", "Salary structure not found", 404)
    return s


def get_structure_components(
    db: Session, structure_id: uuid.UUID,
) -> list[SalaryStructureComponent]:
    return list(db.scalars(select(SalaryStructureComponent).where(
        SalaryStructureComponent.structure_id == structure_id,
    ).order_by(SalaryStructureComponent.created_at.asc())).all())


def list_versions(
    db: Session, group_id: uuid.UUID,
) -> list[SalaryStructure]:
    rows = list(db.scalars(select(SalaryStructure).where(
        SalaryStructure.structure_group_id == group_id,
    ).order_by(SalaryStructure.version_number.asc())).all())
    if not rows:
        raise AppError("not_found", "Salary structure not found", 404)
    return rows


def get_version(
    db: Session, group_id: uuid.UUID, n: int,
) -> SalaryStructure:
    s = db.scalar(select(SalaryStructure).where(
        SalaryStructure.structure_group_id == group_id,
        SalaryStructure.version_number == n,
    ))
    if s is None:
        raise AppError(
            "not_found", "Salary structure version not found", 404,
        )
    return s


def deactivate_group(
    db: Session, user: Any, group_id: uuid.UUID,
) -> None:
    _acquire_group_lock(db, group_id)
    rows = list(db.scalars(select(SalaryStructure).where(
        SalaryStructure.structure_group_id == group_id,
    )).all())
    if not rows:
        raise AppError("not_found", "Salary structure not found", 404)
    for s in rows:
        s.is_active = False
    write_audit(
        db, user,
        entity_type="salary_structure",
        entity_id=rows[0].id,
        action="salary_structure.deactivate_group",
        new_value={"group_id": str(group_id)},
    )

# END OF FILE