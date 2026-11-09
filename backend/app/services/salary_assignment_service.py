"""Salary structure assignment service (Stage C of Milestone 3).

Submit / reject / cancel + read helpers. Approve (with batch inserts,
closures, attempt rows, recovery) is Stage D.

Advisory lock on the employee serialises concurrent submit / approve /
reject / cancel for the same employee. Key derivation is namespace-
isolated from attendance_engine._advisory_lock_key (which uses
(emp_uuid[:4] & 0x7FFFFFFF, days_since_epoch)); here we use a fixed
odd int32 for k1 and a SHA-256 derived int32 for k2, giving provable
namespace separation.

Design points enforced here at submit:
  1. effective_from > today (backdating_not_permitted 422)
  2. at least one pay_period exists (no_pay_periods_configured 409)
  3. effective_from is not affected by any open pay period
     (effective_date_affects_open_period 409)
  4. effective_from is a period boundary (effective_date_not_period_boundary 409)
  5. employee.pay_basis == structure.pay_basis (pay_basis_mismatch 409)
  6. structure.is_current == True (structure_not_current 409)
  7. structure.is_active == True (structure_inactive 409)
  8. no existing pending assignment for employee
     (pending_salary_structure_assignment_exists 409)
  9. no pending individual change requests for employee
     (pending_individual_change_requests_block_assignment 409)
 10. every override_manual_id is a valid manual row of the right kind,
     right employee, right component type, overlapping the effective date
     (invalid_override_manual_id 422 with reason)
 11. no unselected earlier-start manual collision
     (manual_component_type_collision 409)
 12. no same-start manual collision (manual_component_same_start_date 409)
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.scope import ScopeViolation, assert_in_scope
from app.db.tenant.models.change_request import PayrollChangeRequest
from app.db.tenant.models.pay import EmployeeDeduction, EmployeeEarning
from app.db.tenant.models.people import Employee
from app.db.tenant.models.salary_structure import (
    EmployeeSalaryStructureAssignment,
    EmployeeSalaryStructureAssignmentAttempt,
    SalaryStructure,
    SalaryStructureComponent,
)
from app.services.payroll_audit import write_audit


# Namespace prefix + odd int32 salt. Both k1 and k2 are within [0, 2^31)
# so they fit PostgreSQL's int4 (positive range) and cannot be confused
# with attendance_engine's (emp_uuid[:4], days_since_epoch) tuple for any
# realistic employee UUID because k1 is a fixed constant that only an
# astronomically unlucky emp_uuid[:4] could coincidentally match.
_SALT_ASSIGN: int = 0x5A5A7C7D & 0x7FFFFFFF  # 1515879037 (odd)
_NS_ASSIGN = b"payroll.salary_assignment.v1"


def _employee_lock_key(employee_id: uuid.UUID) -> tuple[int, int]:
    k1 = _SALT_ASSIGN
    h = hashlib.sha256(_NS_ASSIGN + employee_id.bytes).digest()
    k2 = int.from_bytes(h[:4], "big", signed=False) & 0x7FFFFFFF
    return k1, k2


def _acquire_employee_lock(db: Session, employee_id: uuid.UUID) -> None:
    k1, k2 = _employee_lock_key(employee_id)
    db.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:k1 AS int), CAST(:k2 AS int))"),
        {"k1": k1, "k2": k2},
    )


# ---------------------------------------------------------------------------
# Inputs / structural helpers
# ---------------------------------------------------------------------------

def _load_employee(db: Session, employee_id: uuid.UUID) -> Employee:
    emp = db.get(Employee, employee_id)
    if emp is None:
        raise AppError("employee_not_found", "Employee not found", 404)
    return emp


def _load_structure(db: Session, structure_id: uuid.UUID) -> SalaryStructure:
    s = db.get(SalaryStructure, structure_id)
    if s is None:
        raise AppError("not_found", "Salary structure not found", 404)
    return s


def _structure_type_pairs(
    db: Session, structure: SalaryStructure,
) -> dict[tuple[str, uuid.UUID], str]:
    """Return {(component_kind, type_id): component_kind} for structure.

    component_kind is 'earning' or 'deduction' — the same discriminator
    used in employee_earning.earning_type_id / employee_deduction.deduction_type_id.
    """
    pairs: dict[tuple[str, uuid.UUID], str] = {}
    comps = db.scalars(select(SalaryStructureComponent).where(
        SalaryStructureComponent.structure_id == structure.id,
    )).all()
    for c in comps:
        if c.kind == "earning" and c.earning_type_id is not None:
            pairs[("earning", c.earning_type_id)] = "earning"
        elif c.kind == "deduction" and c.deduction_type_id is not None:
            pairs[("deduction", c.deduction_type_id)] = "deduction"
    return pairs


# ---------------------------------------------------------------------------
# Date / period rules
# ---------------------------------------------------------------------------

def _validate_date_rules(db: Session, effective_from: date) -> None:
    if effective_from <= date.today():
        raise AppError(
            "backdating_not_permitted",
            "effective_from must be later than today",
            422,
        )

    pay_periods = db.execute(text(
        "SELECT period_key, start_date, end_date, pay_date, status "
        "FROM pay_period"
    )).fetchall()
    if not pay_periods:
        raise AppError(
            "no_pay_periods_configured",
            "No pay periods exist; create a pay-period calendar first",
            409,
        )

    open_affecting = [
        {"period_key": row[0], "pay_date": row[3].isoformat()}
        for row in pay_periods
        if row[4] == "open" and row[3] >= effective_from
    ]
    if open_affecting:
        raise AppError(
            "effective_date_affects_open_period",
            "effective_from affects one or more open pay periods",
            409,
            {"open_periods": open_affecting},
        )

    boundaries: set[date] = set()
    for row in pay_periods:
        boundaries.add(row[1])           # start_date
        boundaries.add(row[2] + timedelta(days=1))  # end_date + 1 day

    if effective_from not in boundaries:
        prior = sorted(b for b in boundaries if b < effective_from)
        nxt = sorted(b for b in boundaries if b > effective_from)
        raise AppError(
            "effective_date_not_period_boundary",
            "effective_from must coincide with a pay-period start or the "
            "day immediately after a pay-period end",
            409,
            {
                "nearest_valid_prior": prior[-1].isoformat() if prior else None,
                "nearest_valid_next": nxt[0].isoformat() if nxt else None,
            },
        )


# ---------------------------------------------------------------------------
# Structure / employee business rules
# ---------------------------------------------------------------------------

def _validate_structure_state(structure: SalaryStructure) -> None:
    if not structure.is_active:
        raise AppError(
            "structure_inactive", "Salary structure group is inactive", 409,
        )
    if not structure.is_current:
        raise AppError(
            "structure_not_current",
            "Only the current version of a structure may be assigned",
            409,
        )


def _validate_pay_basis(emp: Employee, structure: SalaryStructure) -> None:
    if emp.pay_basis != structure.pay_basis:
        raise AppError(
            "pay_basis_mismatch",
            f"Employee pay_basis is {emp.pay_basis!r}; structure is "
            f"{structure.pay_basis!r}",
            409,
        )


def _check_no_pending_assignment(db: Session, employee_id: uuid.UUID) -> None:
    existing = db.scalar(select(EmployeeSalaryStructureAssignment.id).where(
        EmployeeSalaryStructureAssignment.employee_id == employee_id,
        EmployeeSalaryStructureAssignment.status == "pending",
    ))
    if existing is not None:
        raise AppError(
            "pending_salary_structure_assignment_exists",
            "An assignment for this employee is already pending",
            409,
        )


def _check_no_blocking_individual_crs(
    db: Session, employee_id: uuid.UUID,
) -> None:
    blocking = db.scalar(select(PayrollChangeRequest.id).where(
        PayrollChangeRequest.employee_id == employee_id,
        PayrollChangeRequest.status == "pending",
        PayrollChangeRequest.assignment_id.is_(None),
    ))
    if blocking is not None:
        raise AppError(
            "pending_individual_change_requests_block_assignment",
            "Resolve pending individual change requests first",
            409,
        )


# ---------------------------------------------------------------------------
# Manual-overlap classifier
# ---------------------------------------------------------------------------

def _overlap_universe(
    db: Session, employee_id: uuid.UUID,
    structure_type_pairs: dict[tuple[str, uuid.UUID], str],
    effective_from: date,
) -> list[dict]:
    """Return all active manual rows touching effective_from with a
    component type that appears in the structure.

    Each row carries: kind ('employee_earning'|'employee_deduction'),
    id, effective_from, effective_to, component_kind ('earning'|'deduction'),
    component_type_id.
    """
    rows: list[dict] = []

    earn_q = select(EmployeeEarning).where(
        EmployeeEarning.employee_id == employee_id,
        EmployeeEarning.is_active.is_(True),
        EmployeeEarning.source_assignment_id.is_(None),
        EmployeeEarning.effective_from <= effective_from,
    )
    for r in db.scalars(earn_q).all():
        if ("earning", r.earning_type_id) not in structure_type_pairs:
            continue
        # Overlap: earlier start always overlaps; same start overlaps.
        # Exclude if effective_to already fully precedes the assignment.
        if r.effective_to is not None and r.effective_to < effective_from:
            continue
        rows.append({
            "kind": "employee_earning",
            "id": r.id,
            "effective_from": r.effective_from,
            "effective_to": r.effective_to,
            "component_kind": "earning",
            "component_type_id": r.earning_type_id,
        })

    ded_q = select(EmployeeDeduction).where(
        EmployeeDeduction.employee_id == employee_id,
        EmployeeDeduction.is_active.is_(True),
        EmployeeDeduction.source_assignment_id.is_(None),
        EmployeeDeduction.effective_from <= effective_from,
    )
    for r in db.scalars(ded_q).all():
        if ("deduction", r.deduction_type_id) not in structure_type_pairs:
            continue
        if r.effective_to is not None and r.effective_to < effective_from:
            continue
        rows.append({
            "kind": "employee_deduction",
            "id": r.id,
            "effective_from": r.effective_from,
            "effective_to": r.effective_to,
            "component_kind": "deduction",
            "component_type_id": r.deduction_type_id,
        })

    return rows


def _classify_overlaps(
    universe: list[dict],
    selected_set: set[tuple[str, uuid.UUID]],
    effective_from: date,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split universe into (same_start, earlier_selected, earlier_unselected).

    Later-starting rows are not in the universe (query bounds by
    effective_from >= 0 via effective_from <= effective_from filter).
    """
    same_start: list[dict] = []
    earlier_selected: list[dict] = []
    earlier_unselected: list[dict] = []
    for row in universe:
        key = (row["kind"], row["id"])
        if row["effective_from"] == effective_from:
            same_start.append(row)
        elif row["effective_from"] < effective_from:
            if key in selected_set:
                earlier_selected.append(row)
            else:
                earlier_unselected.append(row)
    return same_start, earlier_selected, earlier_unselected


# ---------------------------------------------------------------------------
# override_manual_ids per-item validation
# ---------------------------------------------------------------------------

def _validate_override_manual_ids(
    db: Session, employee_id: uuid.UUID,
    structure_type_pairs: dict[tuple[str, uuid.UUID], str],
    raw_ids: list[dict], effective_from: date,
) -> tuple[set[tuple[str, uuid.UUID]], list[dict]]:
    """Validate each entry; return (selected_set, resolved_rows).

    Raises AppError('invalid_override_manual_id', ..., details={'reason': ...})
    on any structural or ownership failure. Temporal failures are surfaced
    here too: same-start is 409 manual_component_same_start_date; later-
    start or fully-before-range is invalid_override_manual_id reason
    'not_overlapping'.
    """
    selected_set: set[tuple[str, uuid.UUID]] = set()
    resolved: list[dict] = []
    for item in raw_ids:
        kind = item["kind"]            # 'employee_earning' | 'employee_deduction'
        rid = item["id"]

        if kind == "employee_earning":
            row = db.get(EmployeeEarning, rid)
            comp_kind = "earning"
            type_id = row.earning_type_id if row is not None else None
        elif kind == "employee_deduction":
            row = db.get(EmployeeDeduction, rid)
            comp_kind = "deduction"
            type_id = row.deduction_type_id if row is not None else None
        else:
            raise AppError(
                "invalid_override_manual_id",
                "Unknown override kind",
                422,
                {"reason": "bad_kind"},
            )

        if row is None:
            raise AppError(
                "invalid_override_manual_id",
                "Referenced manual row does not exist",
                422,
                {"reason": "not_found"},
            )
        if row.employee_id != employee_id:
            raise AppError(
                "invalid_override_manual_id",
                "Referenced manual row belongs to a different employee",
                422,
                {"reason": "wrong_employee"},
            )
        if not row.is_active:
            raise AppError(
                "invalid_override_manual_id",
                "Referenced manual row is inactive",
                422,
                {"reason": "not_active"},
            )
        if row.source_assignment_id is not None:
            raise AppError(
                "invalid_override_manual_id",
                "Referenced row was created by a prior salary structure",
                422,
                {"reason": "not_manual"},
            )
        if (comp_kind, type_id) not in structure_type_pairs:
            raise AppError(
                "invalid_override_manual_id",
                "Referenced manual row's component type is not in the structure",
                422,
                {"reason": "type_not_in_structure"},
            )

        # Temporal classification (per design §5.6): same-start is
        # its own 409, later-start or fully-before is not_overlapping 422.
        if row.effective_from == effective_from:
            raise AppError(
                "manual_component_same_start_date",
                "A manual component starts on the same day as the assignment",
                409,
            )
        if row.effective_from > effective_from:
            raise AppError(
                "invalid_override_manual_id",
                "Referenced manual row starts after the assignment date",
                422,
                {"reason": "not_overlapping"},
            )
        if row.effective_to is not None and row.effective_to < effective_from:
            raise AppError(
                "invalid_override_manual_id",
                "Referenced manual row ends before the assignment date",
                422,
                {"reason": "not_overlapping"},
            )

        selected_set.add((kind, rid))
        resolved.append({
            "kind": kind,
            "id": rid,
            "component_kind": comp_kind,
            "component_type_id": type_id,
            "effective_from": row.effective_from,
            "effective_to": row.effective_to,
        })

    return selected_set, resolved


# ---------------------------------------------------------------------------
# Public: submit
# ---------------------------------------------------------------------------

def submit_assignment(
    db: Session, user: Any, *,
    employee_id: uuid.UUID,
    structure_id: uuid.UUID,
    effective_from: date,
    idempotency_key: str | None,
    override_manual_ids: list[dict],
) -> EmployeeSalaryStructureAssignment:
    # Idempotency short-circuit (before any lock, so retries are cheap).
    if idempotency_key is not None:
        existing = db.scalar(select(EmployeeSalaryStructureAssignment).where(
            EmployeeSalaryStructureAssignment.idempotency_key == idempotency_key,
        ))
        if existing is not None:
            return existing

    _acquire_employee_lock(db, employee_id)

    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise AppError("employee_not_found", "Employee not found", 404)

    emp = _load_employee(db, employee_id)
    structure = _load_structure(db, structure_id)

    _validate_structure_state(structure)
    _validate_pay_basis(emp, structure)
    _validate_date_rules(db, effective_from)
    _check_no_pending_assignment(db, employee_id)
    _check_no_blocking_individual_crs(db, employee_id)

    type_pairs = _structure_type_pairs(db, structure)
    selected_set, _ = _validate_override_manual_ids(
        db, employee_id, type_pairs, override_manual_ids, effective_from,
    )

    universe = _overlap_universe(db, employee_id, type_pairs, effective_from)
    same_start, _, earlier_unselected = _classify_overlaps(
        universe, selected_set, effective_from,
    )

    # Precedence per design §5.6/§D.6: same-start first, then unselected
    # earlier-start.
    if same_start:
        raise AppError(
            "manual_component_same_start_date",
            "One or more manual components start on the same day as the assignment",
            409,
            {
                "collisions": [
                    {
                        "kind": r["kind"], "id": str(r["id"]),
                        "component_kind": r["component_kind"],
                        "component_type_id": str(r["component_type_id"]),
                    }
                    for r in same_start
                ],
            },
        )
    if earlier_unselected:
        raise AppError(
            "manual_component_type_collision",
            "Manual components overlap the assignment; add them to "
            "override_manual_ids to close them",
            409,
            {
                "collisions": [
                    {
                        "kind": r["kind"], "id": str(r["id"]),
                        "component_kind": r["component_kind"],
                        "component_type_id": str(r["component_type_id"]),
                        "effective_from": r["effective_from"].isoformat(),
                    }
                    for r in earlier_unselected
                ],
            },
        )

    assignment = EmployeeSalaryStructureAssignment(
        employee_id=employee_id,
        structure_id=structure_id,
        effective_from=effective_from,
        status="pending",
        idempotency_key=idempotency_key,
        submitted_by_user_id=getattr(user, "id", None),
        override_manual_ids=[
            {"kind": i["kind"], "id": str(i["id"])} for i in override_manual_ids
        ],
    )
    db.add(assignment)
    db.flush()
    write_audit(
        db, user,
        entity_type="salary_assignment",
        entity_id=assignment.id,
        action="salary_assignment.submit",
        new_value={
            "employee_id": str(employee_id),
            "structure_id": str(structure_id),
            "effective_from": effective_from.isoformat(),
            "override_manual_ids": [
                {"kind": i["kind"], "id": str(i["id"])} for i in override_manual_ids
            ],
        },
    )
    return assignment


# ---------------------------------------------------------------------------
# Public: reject / cancel
# ---------------------------------------------------------------------------

def _load_pending_assignment(
    db: Session, assignment_id: uuid.UUID,
) -> EmployeeSalaryStructureAssignment:
    a = db.scalar(select(EmployeeSalaryStructureAssignment).where(
        EmployeeSalaryStructureAssignment.id == assignment_id,
    ).with_for_update())
    if a is None:
        raise AppError("not_found", "Assignment not found", 404)
    if a.status != "pending":
        raise AppError(
            "not_pending",
            f"Assignment is {a.status}, cannot transition",
            409,
        )
    return a


def reject_assignment(
    db: Session, user: Any, assignment_id: uuid.UUID, note: str,
) -> EmployeeSalaryStructureAssignment:
    a = db.get(EmployeeSalaryStructureAssignment, assignment_id)
    if a is None:
        raise AppError("not_found", "Assignment not found", 404)
    _acquire_employee_lock(db, a.employee_id)
    a = _load_pending_assignment(db, assignment_id)

    if a.submitted_by_user_id == getattr(user, "id", None):
        raise AppError(
            "self_approval_forbidden",
            "Approver must differ from submitter",
            409,
        )

    a.status = "rejected"
    a.decided_by_user_id = getattr(user, "id", None)
    a.decided_at = datetime.utcnow()
    a.decision_note = note
    a.row_version += 1

    db.add(EmployeeSalaryStructureAssignmentAttempt(
        assignment_id=a.id,
        attempted_by_user_id=getattr(user, "id", None),
        outcome="rejected",
    ))
    write_audit(
        db, user,
        entity_type="salary_assignment",
        entity_id=a.id,
        action="salary_assignment.reject",
        old_value={"status": "pending"},
        new_value={"status": "rejected", "note": note},
    )
    db.flush()
    return a


def cancel_assignment(
    db: Session, user: Any, assignment_id: uuid.UUID,
) -> EmployeeSalaryStructureAssignment:
    a = db.get(EmployeeSalaryStructureAssignment, assignment_id)
    if a is None:
        raise AppError("not_found", "Assignment not found", 404)
    _acquire_employee_lock(db, a.employee_id)
    a = _load_pending_assignment(db, assignment_id)

    if a.submitted_by_user_id != getattr(user, "id", None):
        raise AppError(
            "not_requester",
            "Only the requester may cancel a pending assignment",
            403,
        )

    a.status = "cancelled"
    a.row_version += 1

    db.add(EmployeeSalaryStructureAssignmentAttempt(
        assignment_id=a.id,
        attempted_by_user_id=getattr(user, "id", None),
        outcome="cancelled",
    ))
    write_audit(
        db, user,
        entity_type="salary_assignment",
        entity_id=a.id,
        action="salary_assignment.cancel",
        old_value={"status": "pending"},
        new_value={"status": "cancelled"},
    )
    db.flush()
    return a


# ---------------------------------------------------------------------------
# Public: read helpers
# ---------------------------------------------------------------------------

def get_assignment(
    db: Session, user: Any, assignment_id: uuid.UUID,
) -> EmployeeSalaryStructureAssignment:
    a = db.get(EmployeeSalaryStructureAssignment, assignment_id)
    if a is None:
        raise AppError("not_found", "Assignment not found", 404)
    try:
        assert_in_scope(user, a.employee_id, db)
    except ScopeViolation:
        raise AppError("not_found", "Assignment not found", 404)
    return a


def list_children(
    db: Session, assignment_id: uuid.UUID,
) -> list[PayrollChangeRequest]:
    return list(db.scalars(select(PayrollChangeRequest).where(
        PayrollChangeRequest.assignment_id == assignment_id,
    ).order_by(PayrollChangeRequest.requested_at.asc())).all())


def list_attempts(
    db: Session, user: Any, assignment_id: uuid.UUID,
) -> list[EmployeeSalaryStructureAssignmentAttempt]:
    get_assignment(db, user, assignment_id)  # raises if out of scope
    return list(db.scalars(select(EmployeeSalaryStructureAssignmentAttempt).where(
        EmployeeSalaryStructureAssignmentAttempt.assignment_id == assignment_id,
    ).order_by(EmployeeSalaryStructureAssignmentAttempt.attempted_at.desc())).all())


def list_for_employee(
    db: Session, user: Any, employee_id: uuid.UUID,
) -> list[EmployeeSalaryStructureAssignment]:
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise AppError("employee_not_found", "Employee not found", 404)
    return list(db.scalars(select(EmployeeSalaryStructureAssignment).where(
        EmployeeSalaryStructureAssignment.employee_id == employee_id,
    ).order_by(EmployeeSalaryStructureAssignment.submitted_at.desc())).all())


# ---------------------------------------------------------------------------
# Public: collision pre-check (read-only)
# ---------------------------------------------------------------------------

def check_collisions(
    db: Session, user: Any, *,
    employee_id: uuid.UUID,
    structure_id: uuid.UUID,
    effective_from: date,
    override_manual_ids: list[dict],
) -> dict:
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise AppError("employee_not_found", "Employee not found", 404)

    structure = _load_structure(db, structure_id)
    type_pairs = _structure_type_pairs(db, structure)

    # Do not raise on bad override_manual_ids here — pre-check is a hint
    # generator, so tolerate missing / mismatched ids and just skip them.
    selected_set: set[tuple[str, uuid.UUID]] = set()
    for item in override_manual_ids:
        selected_set.add((item["kind"], item["id"]))

    universe = _overlap_universe(db, employee_id, type_pairs, effective_from)
    same_start, earlier_selected, earlier_unselected = _classify_overlaps(
        universe, selected_set, effective_from,
    )

    def _row_payload(r: dict, status: str) -> dict:
        return {
            "kind": r["kind"],
            "id": str(r["id"]),
            "component_kind": r["component_kind"],
            "component_type_id": str(r["component_type_id"]),
            "effective_from": r["effective_from"].isoformat(),
            "effective_to": (
                r["effective_to"].isoformat() if r["effective_to"] else None
            ),
            "status": status,
        }

    manual: list[dict] = []
    for r in earlier_unselected:
        manual.append(_row_payload(r, "requires_override"))
    for r in earlier_selected:
        manual.append(_row_payload(r, "will_close"))
    for r in same_start:
        manual.append(_row_payload(r, "cannot_close_same_start"))

    # Structure-owned rows (created by a prior assignment). They close
    # automatically — the frontend displays them for transparency.
    structure_owned: list[dict] = []
    for model, kind, type_attr in (
        (EmployeeEarning, "employee_earning", "earning_type_id"),
        (EmployeeDeduction, "employee_deduction", "deduction_type_id"),
    ):
        rows = db.scalars(select(model).where(
            model.employee_id == employee_id,
            model.is_active.is_(True),
            model.source_assignment_id.is_not(None),
            model.effective_from <= effective_from,
        )).all()
        for r in rows:
            tid = getattr(r, type_attr)
            comp_kind = "earning" if kind == "employee_earning" else "deduction"
            if (comp_kind, tid) not in type_pairs:
                continue
            if r.effective_to is not None and r.effective_to < effective_from:
                continue
            structure_owned.append({
                "kind": kind,
                "id": str(r.id),
                "component_kind": comp_kind,
                "component_type_id": str(tid),
                "effective_from": r.effective_from.isoformat(),
                "effective_to": r.effective_to.isoformat() if r.effective_to else None,
            })

    return {
        "employee_id": str(employee_id),
        "structure_id": str(structure_id),
        "effective_from": effective_from.isoformat(),
        "manual": manual,
        "structure_owned": structure_owned,
    }

# END OF FILE