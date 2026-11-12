"""Salary assignment approve service (Stage D of Milestone 3).

Batch approval with:
  * employee advisory lock (same key as submit/reject/cancel)
  * all Phase A business rechecks under the lock
  * Phase B savepoint-wrapped batch work (closures + inserts + children)
  * Phase C attempt row + status flip + audit, all inside the outer txn
  * Phase D outer commit (this function DOES commit — unlike submit/reject/
    cancel, which let the router commit; the design requires recovery to own
    its own commit path)
  * failure-recovery helper that commits a failed attempt after the outer
    txn rolls back, WITHOUT touching terminal assignments (reacquires the
    same lock, reloads, checks status under lock)

M6 Part 2 Stage 2b: Phase A now also refuses with 409 locked_period_affects
if any locked pay period has `end_date >= assignment.effective_from`.
Approving the assignment inserts new effective-dated rows starting at
`effective_from` and closes prior manual/structure-owned rows at
`effective_from - 1`; both operations can alter any locked period whose
window extends to or past `effective_from`. Closing rows at
`effective_from - 1` is provably safe for locked periods that end at or
before that day, so the single comparison is both necessary and sufficient.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tenant.models.change_request import PayrollChangeRequest
from app.db.tenant.models.pay import (
    DeductionType, EarningType, EmployeeDeduction, EmployeeEarning, PayPeriod,
)
from app.db.tenant.models.people import Employee, EmployeePayHistory
from app.db.tenant.models.salary_structure import (
    EmployeeSalaryStructureAssignment,
    EmployeeSalaryStructureAssignmentAttempt,
    SalaryStructure,
    SalaryStructureComponent,
)
from app.services.payroll_audit import write_audit
from app.services.salary_assignment_service import (
    acquire_employee_lock,
    classify_overlaps,
    overlap_universe,
    structure_type_pairs,
    validate_date_rules,
    validate_pay_basis,
    validate_structure_state,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_MONTHLY_CRITICAL: tuple[str, ...] = (
    "calc_method", "frequency", "is_taxable",
    "counts_for_uif", "counts_for_sdl", "proration_rule",
)

_BASE_MONTHLY_CANONICAL: dict[str, Any] = {
    "calc_method": "fixed_amount",
    "frequency": "regular",
    "is_taxable": True,
    "counts_for_uif": True,
    "counts_for_sdl": True,
    "proration_rule": "none",
}

_WHITELISTED_CONSTRAINTS: frozenset[str] = frozenset({
    "uq_pending_assignment_per_employee",
    "uq_open_approved_assignment",
    "uq_assignment_idempotency",
    "uq_salary_structure_group_version",
    "uq_salary_structure_current",
    "ck_employee_earning_amount_or_rate",
    "ck_salary_structure_component_type_exclusive",
    "ck_salary_structure_component_amount_or_rate",
    "ck_assignment_status",
    "ck_assignment_effective_range",
    "ck_assignment_attempt_outcome",
    "ck_assignment_attempt_failure_detail",
})


# ---------------------------------------------------------------------------
# ensure_base_monthly_type
# ---------------------------------------------------------------------------

def ensure_base_monthly_type(db: Session) -> EarningType:
    """Get or create BASE_MONTHLY. Never overwrites an existing row."""
    existing = db.scalar(select(EarningType).where(
        EarningType.code == "BASE_MONTHLY",
    ))
    if existing is None:
        et = EarningType(
            code="BASE_MONTHLY",
            name="Base Monthly Salary",
            calc_method=_BASE_MONTHLY_CANONICAL["calc_method"],
            frequency=_BASE_MONTHLY_CANONICAL["frequency"],
            is_taxable=_BASE_MONTHLY_CANONICAL["is_taxable"],
            counts_for_uif=_BASE_MONTHLY_CANONICAL["counts_for_uif"],
            counts_for_sdl=_BASE_MONTHLY_CANONICAL["counts_for_sdl"],
            proration_rule=_BASE_MONTHLY_CANONICAL["proration_rule"],
            is_system=False,
            is_active=True,
            row_version=1,
        )
        db.add(et)
        db.flush()
        return et

    if not existing.is_active:
        raise AppError(
            "base_monthly_type_inactive",
            "BASE_MONTHLY earning type exists but is inactive",
            409,
        )
    diffs = {
        f: {"expected": _BASE_MONTHLY_CANONICAL[f], "actual": getattr(existing, f)}
        for f in _BASE_MONTHLY_CRITICAL
        if getattr(existing, f) != _BASE_MONTHLY_CANONICAL[f]
    }
    if diffs:
        raise AppError(
            "base_monthly_type_config_mismatch",
            "Existing BASE_MONTHLY earning type has mismatched critical fields",
            409,
            {"field_diffs": diffs},
        )
    return existing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _whitelist_constraint(exc: BaseException) -> str:
    try:
        orig = getattr(exc, "orig", None)
        diag = getattr(orig, "diag", None)
        name = getattr(diag, "constraint_name", None)
    except Exception:
        return "unknown"
    return name if name in _WHITELISTED_CONSTRAINTS else "unknown"


def _overlap_exists(db: Session, employee_id: uuid.UUID, effective_from: date) -> bool:
    row = db.scalar(select(EmployeePayHistory.id).where(
        EmployeePayHistory.employee_id == employee_id,
        EmployeePayHistory.effective_from == effective_from,
        EmployeePayHistory.status.in_(("pending", "approved")),
    ))
    return row is not None


def _effective_ordering_check(
    db: Session, a: EmployeeSalaryStructureAssignment,
) -> None:
    latest = db.scalar(select(EmployeeSalaryStructureAssignment).where(
        EmployeeSalaryStructureAssignment.employee_id == a.employee_id,
        EmployeeSalaryStructureAssignment.status == "approved",
        EmployeeSalaryStructureAssignment.id != a.id,
    ).order_by(
        EmployeeSalaryStructureAssignment.effective_from.desc(),
    ).limit(1))
    if latest is not None and a.effective_from <= latest.effective_from:
        raise AppError(
            "assignment_effective_date_not_after_latest_approved",
            "effective_from must be later than the latest approved assignment",
            409,
            {"latest_approved_effective_from": latest.effective_from.isoformat()},
        )


def _recheck_closure_consistency(
    db: Session, a: EmployeeSalaryStructureAssignment,
) -> None:
    """Re-run universe classification under the lock.

    Verifies:
      * no same-start manual collisions (manual_component_same_start_date)
      * no unselected earlier-start manual collisions
        (manual_component_type_collision)
      * every override_manual_id still corresponds to an eligible earlier-
        start row (else close_set_mismatch)
    """
    structure = db.get(SalaryStructure, a.structure_id)
    if structure is None:
        raise AppError("not_found", "Salary structure not found", 404)
    type_pairs = structure_type_pairs(db, structure)

    selected_set: set[tuple[str, uuid.UUID]] = set()
    for item in a.override_manual_ids:
        selected_set.add((item["kind"], uuid.UUID(item["id"])))

    universe = overlap_universe(db, a.employee_id, type_pairs, a.effective_from)
    same_start, earlier_selected, earlier_unselected = classify_overlaps(
        universe, selected_set, a.effective_from,
    )

    if same_start:
        raise AppError(
            "manual_component_same_start_date",
            "Manual components start on the same day as the assignment",
            409,
            {"collisions": [
                {"kind": r["kind"], "id": str(r["id"])} for r in same_start
            ]},
        )
    if earlier_unselected:
        raise AppError(
            "manual_component_type_collision",
            "Manual components overlap the assignment and are not selected for closure",
            409,
            {"collisions": [
                {"kind": r["kind"], "id": str(r["id"])} for r in earlier_unselected
            ]},
        )
    actual_selected = {(r["kind"], r["id"]) for r in earlier_selected}
    missing = selected_set - actual_selected
    if missing:
        raise AppError(
            "close_set_mismatch",
            "One or more selected manual overrides are no longer eligible",
            409,
            {"manual": {
                "selected_not_actual": [
                    {"kind": k, "id": str(i)} for k, i in missing
                ],
            }},
        )


def _locked_period_guard(
    db: Session, a: EmployeeSalaryStructureAssignment,
) -> None:
    """M6 Part 2 Stage 2b: refuse if approving the assignment would alter
    any locked pay period.

    Approving inserts new effective-dated rows starting at a.effective_from
    and closes prior manual/structure-owned rows at a.effective_from - 1.
    For a locked period [S, E]:
      * E < a.effective_from → new rows never enter the period; closes at
        a.effective_from - 1 keep prior rows active through E → no change.
      * E >= a.effective_from → new rows enter on [max(S, effective_from), E]
        and/or prior rows stop before a.effective_from → period's payslips
        would differ on recompute.

    Single comparison is necessary and sufficient.
    """
    locked = db.scalar(
        select(PayPeriod)
        .where(
            PayPeriod.status == "locked",
            PayPeriod.end_date >= a.effective_from,
        )
        .limit(1)
    )
    if locked is not None:
        raise AppError(
            "locked_period_affects",
            f"approving this assignment would alter locked period "
            f"{locked.period_key!r}; reopen the period first",
            409,
            {
                "period_id": str(locked.id),
                "period_key": locked.period_key,
                "assignment_id": str(a.id),
                "effective_from": a.effective_from.isoformat(),
            },
        )


# ---------------------------------------------------------------------------
# Phase B — batch work
# ---------------------------------------------------------------------------

def _create_child(
    db: Session, a: EmployeeSalaryStructureAssignment, user: Any,
    *, kind: str, payload: dict, applied_entity_id: uuid.UUID,
) -> PayrollChangeRequest:
    now = datetime.now()
    child = PayrollChangeRequest(
        id=uuid.uuid4(),
        kind=kind,
        employee_id=a.employee_id,
        payload=payload,
        status="approved",
        requested_by_user_id=getattr(user, "id", None),
        decided_by_user_id=getattr(user, "id", None),
        decided_at=now,
        decision_note="Applied via salary structure assignment "
                      f"{a.id}",
        applied_entity_id=applied_entity_id,
        assignment_id=a.id,
        row_version=1,
    )
    db.add(child)
    db.flush()
    return child


def _close_manual_overrides(
    db: Session, a: EmployeeSalaryStructureAssignment, user: Any,
) -> list[dict]:
    closed: list[dict] = []
    close_to = a.effective_from - timedelta(days=1)
    for item in a.override_manual_ids:
        kind = item["kind"]
        rid = uuid.UUID(item["id"])
        if kind == "employee_earning":
            row = db.get(EmployeeEarning, rid)
            if row is None:
                continue
            row.effective_to = close_to
            row.row_version += 1
            db.flush()
            _create_child(
                db, a, user,
                kind="employee_earning_deactivate",
                payload={"target_id": str(rid), "reason": "structure_overridden"},
                applied_entity_id=rid,
            )
            closed.append({"kind": kind, "id": rid})
        elif kind == "employee_deduction":
            row = db.get(EmployeeDeduction, rid)
            if row is None:
                continue
            row.effective_to = close_to
            row.row_version += 1
            db.flush()
            _create_child(
                db, a, user,
                kind="employee_deduction_deactivate",
                payload={"target_id": str(rid), "reason": "structure_overridden"},
                applied_entity_id=rid,
            )
            closed.append({"kind": kind, "id": rid})
    return closed


def _close_prior_structure_rows(
    db: Session, a: EmployeeSalaryStructureAssignment, user: Any,
) -> list[dict]:
    closed: list[dict] = []
    close_to = a.effective_from - timedelta(days=1)
    for model, kind, child_kind in (
        (EmployeeEarning, "employee_earning", "employee_earning_deactivate"),
        (EmployeeDeduction, "employee_deduction", "employee_deduction_deactivate"),
    ):
        rows = db.scalars(select(model).where(
            model.employee_id == a.employee_id,
            model.is_active.is_(True),
            model.source_assignment_id.is_not(None),
            model.source_assignment_id != a.id,
            model.effective_to.is_(None),
        )).all()
        for r in rows:
            if r.effective_from >= a.effective_from:
                continue
            r.effective_to = close_to
            r.row_version += 1
            db.flush()
            _create_child(
                db, a, user,
                kind=child_kind,
                payload={"target_id": str(r.id), "reason": "structure_assigned"},
                applied_entity_id=r.id,
            )
            closed.append({"kind": kind, "id": r.id})
    return closed


def _insert_component_rows(
    db: Session, a: EmployeeSalaryStructureAssignment, user: Any,
    structure: SalaryStructure,
) -> None:
    comps = db.scalars(select(SalaryStructureComponent).where(
        SalaryStructureComponent.structure_id == structure.id,
    )).all()
    for c in comps:
        if c.kind == "earning":
            row = EmployeeEarning(
                id=uuid.uuid4(),
                employee_id=a.employee_id,
                earning_type_id=c.earning_type_id,
                amount=c.amount,
                rate=c.rate,
                effective_from=a.effective_from,
                effective_to=None,
                is_active=True,
                source_assignment_id=a.id,
                row_version=1,
            )
            db.add(row)
            db.flush()
            _create_child(
                db, a, user,
                kind="employee_earning_create",
                payload={
                    "earning_type_id": str(c.earning_type_id),
                    "amount": str(c.amount) if c.amount is not None else None,
                    "rate": str(c.rate) if c.rate is not None else None,
                    "effective_from": a.effective_from.isoformat(),
                },
                applied_entity_id=row.id,
            )
        elif c.kind == "deduction":
            row = EmployeeDeduction(
                id=uuid.uuid4(),
                employee_id=a.employee_id,
                deduction_type_id=c.deduction_type_id,
                amount=c.amount,
                balance=Decimal("0"),
                effective_from=a.effective_from,
                effective_to=None,
                is_active=True,
                source_assignment_id=a.id,
                row_version=1,
            )
            db.add(row)
            db.flush()
            _create_child(
                db, a, user,
                kind="employee_deduction_create",
                payload={
                    "deduction_type_id": str(c.deduction_type_id),
                    "amount": str(c.amount),
                    "effective_from": a.effective_from.isoformat(),
                },
                applied_entity_id=row.id,
            )


def _insert_monthly_base(
    db: Session, a: EmployeeSalaryStructureAssignment, user: Any,
    structure: SalaryStructure,
) -> None:
    base = ensure_base_monthly_type(db)
    row = EmployeeEarning(
        id=uuid.uuid4(),
        employee_id=a.employee_id,
        earning_type_id=base.id,
        amount=structure.base_rate,
        rate=None,
        effective_from=a.effective_from,
        effective_to=None,
        is_active=True,
        source_assignment_id=a.id,
        row_version=1,
    )
    db.add(row)
    db.flush()
    _create_child(
        db, a, user,
        kind="employee_earning_create",
        payload={
            "earning_type_id": str(base.id),
            "amount": str(structure.base_rate),
            "effective_from": a.effective_from.isoformat(),
        },
        applied_entity_id=row.id,
    )


def _insert_hourly_rate(
    db: Session, a: EmployeeSalaryStructureAssignment, user: Any,
    structure: SalaryStructure,
) -> None:
    if _overlap_exists(db, a.employee_id, a.effective_from):
        raise AppError(
            "overlapping_rate_effective_date",
            "A pay-rate change already exists on this effective date",
            409,
            {"effective_from": a.effective_from.isoformat()},
        )
    now = datetime.now()
    ph = EmployeePayHistory(
        id=uuid.uuid4(),
        employee_id=a.employee_id,
        base_rate=structure.base_rate,
        effective_from=a.effective_from,
        changed_by=getattr(user, "id", None),
        approved_by=getattr(user, "id", None),
        decided_by=getattr(user, "id", None),
        decided_at=now,
        decision_reason="Structure assignment " + str(a.id),
        source="structure_assignment",
        status="approved",
        source_assignment_id=a.id,
    )
    db.add(ph)
    db.flush()
    latest = db.scalar(select(EmployeePayHistory).where(
        EmployeePayHistory.employee_id == a.employee_id,
        EmployeePayHistory.status == "approved",
        EmployeePayHistory.effective_from <= date.today(),
    ).order_by(
        EmployeePayHistory.effective_from.desc(),
        EmployeePayHistory.decided_at.desc(),
        EmployeePayHistory.id.desc(),
    ).limit(1))
    if latest is not None and latest.id == ph.id:
        emp = db.get(Employee, a.employee_id)
        if emp is not None:
            emp.base_rate = structure.base_rate


def _close_prior_open_assignment(
    db: Session, a: EmployeeSalaryStructureAssignment,
) -> None:
    prior = db.scalar(select(EmployeeSalaryStructureAssignment).where(
        EmployeeSalaryStructureAssignment.employee_id == a.employee_id,
        EmployeeSalaryStructureAssignment.status == "approved",
        EmployeeSalaryStructureAssignment.effective_to.is_(None),
        EmployeeSalaryStructureAssignment.id != a.id,
    ))
    if prior is None:
        return
    prior.effective_to = a.effective_from - timedelta(days=1)
    prior.row_version += 1
    db.flush()


# ---------------------------------------------------------------------------
# Recovery helper
# ---------------------------------------------------------------------------

def _record_failed_attempt_and_reraise(
    db: Session,
    assignment_id: uuid.UUID,
    employee_id: uuid.UUID,
    user: Any,
    kind: str,  # "integrity" | "unexpected"
    error: BaseException,
    rid: str,
) -> None:
    try:
        db.rollback()
    except Exception:
        try:
            db.close()
        except Exception:
            pass
        raise AppError(
            "failure_recording_failed",
            "Failed to roll back original transaction",
            500,
            {"assignment_id": str(assignment_id), "request_id": rid},
        ) from None

    attempt = None
    try:
        acquire_employee_lock(db, employee_id)
        assignment = db.get(EmployeeSalaryStructureAssignment, assignment_id)
        if assignment is None:
            raise AppError(
                "internal_invariant_violation",
                "Assignment vanished during recovery",
                500,
                {"request_id": rid},
            )
        if assignment.status != "pending":
            raise AppError(
                "assignment_state_conflict",
                "Assignment is no longer pending",
                409,
                {"request_id": rid},
            )
        attempt = EmployeeSalaryStructureAssignmentAttempt(
            assignment_id=assignment_id,
            outcome="failed",
            attempted_by_user_id=getattr(user, "id", None),
            failure_detail=(
                f"integrity_violation:{_whitelist_constraint(error)}"
                if kind == "integrity"
                else f"unexpected_error:{rid}"
            ),
        )
        db.add(attempt)
        write_audit(
            db, user,
            entity_type="salary_assignment",
            entity_id=assignment_id,
            action="salary_assignment.approve_failed",
            new_value={"category": kind, "request_id": rid},
        )
        db.commit()
    except AppError:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise AppError(
            "failure_recording_failed",
            "Failed to record failed attempt",
            500,
            {"assignment_id": str(assignment_id), "request_id": rid},
        ) from None

    if kind == "integrity":
        raise AppError(
            "approval_batch_failed",
            "Approval batch failed",
            409,
            {"assignment_id": str(assignment_id), "attempt_id": str(attempt.id)},
        )
    raise AppError(
        "approval_unexpected_error",
        "Unexpected error during approval",
        500,
        {"assignment_id": str(assignment_id), "attempt_id": str(attempt.id),
         "request_id": rid},
    )


# ---------------------------------------------------------------------------
# Public: approve
# ---------------------------------------------------------------------------

def approve_assignment(
    db: Session, user: Any, assignment_id: uuid.UUID,
) -> EmployeeSalaryStructureAssignment:
    rid = uuid.uuid4().hex
    a_pre = db.get(EmployeeSalaryStructureAssignment, assignment_id)
    if a_pre is None:
        raise AppError("not_found", "Assignment not found", 404)
    employee_id = a_pre.employee_id

    try:
        return _do_approve(db, user, assignment_id, employee_id, rid)
    except AppError:
        raise
    except IntegrityError as exc:
        _record_failed_attempt_and_reraise(
            db, assignment_id, employee_id, user, "integrity", exc, rid,
        )
        return None  # unreachable
    except Exception as exc:
        _record_failed_attempt_and_reraise(
            db, assignment_id, employee_id, user, "unexpected", exc, rid,
        )
        return None  # unreachable


def _do_approve(
    db: Session, user: Any, assignment_id: uuid.UUID,
    employee_id: uuid.UUID, rid: str,
) -> EmployeeSalaryStructureAssignment:
    # ---- Phase A: lock + all pre-checks ----
    acquire_employee_lock(db, employee_id)

    a = db.scalar(select(EmployeeSalaryStructureAssignment).where(
        EmployeeSalaryStructureAssignment.id == assignment_id,
    ).with_for_update())
    if a is None:
        raise AppError("not_found", "Assignment not found", 404)
    if a.status != "pending":
        raise AppError(
            "not_pending",
            f"Assignment is {a.status}, cannot approve",
            409,
        )
    if a.submitted_by_user_id == getattr(user, "id", None):
        raise AppError(
            "self_approval_forbidden",
            "Approver must differ from submitter",
            409,
        )

    emp = db.get(Employee, a.employee_id)
    structure = db.get(SalaryStructure, a.structure_id)
    if emp is None or structure is None:
        raise AppError("not_found", "Employee or structure not found", 404)

    validate_structure_state(structure)
    validate_pay_basis(emp, structure)
    validate_date_rules(db, a.effective_from)
    _effective_ordering_check(db, a)
    _recheck_closure_consistency(db, a)

    # M6 Part 2 Stage 2b: locked-period guard. Runs last in Phase A so the
    # user gets assignment-specific error messages first, then the
    # environmental one. Raises before Phase B's savepoint opens, so a
    # blocked approval leaves zero residue.
    _locked_period_guard(db, a)

    # ---- Phase B: batch work inside a savepoint ----
    sp = db.begin_nested()
    try:
        _close_manual_overrides(db, a, user)
        _close_prior_structure_rows(db, a, user)
        _insert_component_rows(db, a, user, structure)
        if structure.pay_basis == "monthly":
            _insert_monthly_base(db, a, user, structure)
        elif structure.pay_basis in ("hourly", "daily"):
            _insert_hourly_rate(db, a, user, structure)
        _close_prior_open_assignment(db, a)
        sp.commit()
    except BaseException:
        sp.rollback()
        raise

    # ---- Phase C: attempt row + status + audit (inside outer txn) ----
    db.add(EmployeeSalaryStructureAssignmentAttempt(
        assignment_id=a.id,
        outcome="approved",
        attempted_by_user_id=getattr(user, "id", None),
    ))
    a.status = "approved"
    a.decided_by_user_id = getattr(user, "id", None)
    a.decided_at = datetime.now()
    a.row_version += 1
    write_audit(
        db, user,
        entity_type="salary_assignment",
        entity_id=a.id,
        action="salary_assignment.approve",
        old_value={"status": "pending"},
        new_value={"status": "approved"},
    )
    children = db.scalars(select(PayrollChangeRequest).where(
        PayrollChangeRequest.assignment_id == a.id,
    )).all()
    for child in children:
        write_audit(
            db, user,
            entity_type="payroll_change_request",
            entity_id=child.id,
            action="payroll_change_request.approve_via_assignment",
            old_value={"status": "pending"},
            new_value={"status": "approved"},
        )

    # ---- Phase D: outer commit ----
    db.commit()
    db.refresh(a)
    return a

# END OF FILE