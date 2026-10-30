"""Payroll runner (Chapter 4, Bundle 004b-a).

Orchestration layer between HTTP endpoints and the pure pipeline:

  build_pipeline_config(db, employee, pay_date) -> PipelineConfig
  run_preview(db, user, pay_period) -> PayrollRun
  finalise(db, user, pay_period) -> PayrollRun
  reopen(db, user, pay_period, reason) -> PeriodReopenLog

Earnings source for 016a (documented limitation, Chapter 5 will integrate
attendance): EmployeeEarning rows with calc_method == 'fixed_amount'. A
per_hour earning raises calc_method_unsupported.

Reimbursements are always empty in 016a - no reimbursement source table
exists in migration 0017 yet.

Preview is persisted per F4: one payroll_run(kind='preview') + payslip rows
with status='preview'. Re-running preview purges the prior preview for that
period. Previews are excluded from /payslips and /pay/me/payslips.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tenant.models.pay import (
    EarningType, EmployeeEarning, EmployeeDeduction, DeductionType,
    PayPeriod, PayrollRun, Payslip, PayslipLine, PeriodReopenLog,
)
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.people import Employee
from app.services import payroll_pipeline as P
from app.services import payroll_tax as T
from app.services.payroll_audit import write_audit
from app.services.payroll_formulas import FORMULA_REGISTRY
from app.services.payroll_seed import ensure_system_earning_types
from app.services.statutory_loader import _default_engine, get_active_table


_PERIODS_PER_YEAR = {"monthly": 12, "weekly": 52, "fortnightly": 26}


# ---------------------------------------------------------------------------
# Settings + config
# ---------------------------------------------------------------------------

def _load_settings(db: Session) -> PayrollSettings:
    settings = db.scalar(select(PayrollSettings).limit(1))
    if settings is None:
        raise AppError(
            "settings_missing",
            "Payroll settings have not been created yet; call PATCH /payroll/settings first",
            409,
        )
    return settings


def _load_control_table(table_type: str, on_date: date) -> list[dict]:
    engine = _default_engine()
    row = get_active_table(engine, "ZA", table_type, on_date)
    if row is None:
        raise AppError(
            "statutory_table_missing",
            f"ZA/{table_type} has no active version covering {on_date.isoformat()}",
            409,
        )
    return row["rows"]


def _resolve_age(employee: Employee, on_date: date, age_ref: str) -> int:
    if employee.date_of_birth is None:
        raise AppError("missing_date_of_birth", "employee.date_of_birth is null", 409)
    return T.compute_age(employee.date_of_birth, on_date)


def build_pipeline_config(
    db: Session, employee: Employee, pay_date: date,
) -> P.PipelineConfig:
    settings = _load_settings(db)
    if settings.sdl_applies is None:
        raise AppError("sdl_applies_unset", "payroll.sdl_applies is unset", 409)
    if settings.age_reference_date is None:
        raise AppError("age_reference_date_unset", "payroll.age_reference_date is unset", 409)
    if employee.pay_frequency not in _PERIODS_PER_YEAR:
        raise AppError(
            "unsupported_pay_frequency",
            f"pay_frequency {employee.pay_frequency!r} not supported",
            409,
        )

    age_ref = settings.age_reference_date
    age_date = pay_date  # v1: all three modes resolve to pay_date; finer rules deferred
    age = _resolve_age(employee, age_date, age_ref)

    control_engine = _default_engine()
    tax_tables = T.load_tax_tables(control_engine, pay_date)

    return P.PipelineConfig(
        tax_engine=T.default_engine(),
        tax_tables=tax_tables,
        uif_rows=_load_control_table("uif", pay_date),
        sdl_rows=_load_control_table("sdl", pay_date),
        retirement_rows=_load_control_table("retirement_limit", pay_date),
        periods_per_year=_PERIODS_PER_YEAR[employee.pay_frequency],
        employee_age=age,
        medical_members=employee.medical_scheme_members or 0,
        uif_exempt=bool(employee.uif_exempt),
        sdl_applies=settings.sdl_applies,
        net_pay_floor=settings.net_pay_floor or Decimal("0.00"),
    )


# ---------------------------------------------------------------------------
# Earnings / deductions builders
# ---------------------------------------------------------------------------

def _build_earnings(db: Session, employee: Employee, on_date: date) -> list[P.EarningLine]:
    rows = db.scalars(
        select(EmployeeEarning).where(
            EmployeeEarning.employee_id == employee.id,
            EmployeeEarning.is_active.is_(True),
            EmployeeEarning.effective_from <= on_date,
        )
    ).all()
    lines: list[P.EarningLine] = []
    for r in rows:
        if r.effective_to is not None and r.effective_to < on_date:
            continue
        et = db.scalar(select(EarningType).where(EarningType.id == r.earning_type_id))
        if et is None:
            raise AppError(
                "earning_type_missing",
                f"employee_earning {r.id} references missing earning_type",
                500,
            )
        if et.calc_method != "fixed_amount":
            raise AppError(
                "calc_method_unsupported",
                f"earning_type {et.code!r} has calc_method {et.calc_method!r}; "
                f"only 'fixed_amount' is supported in this release",
                409,
            )
        if r.amount is None:
            raise AppError(
                "amount_missing",
                f"employee_earning {r.id} has null amount with fixed_amount calc_method",
                500,
            )
        lines.append(P.EarningLine(
            label=et.name,
            amount=Decimal(r.amount),
            frequency=et.frequency,
            is_taxable=bool(et.is_taxable),
            counts_for_uif=bool(et.counts_for_uif),
            counts_for_sdl=bool(et.counts_for_sdl),
            source_ref={"employee_earning_id": str(r.id), "earning_type_code": et.code},
        ))
    return lines


def _build_deductions(db: Session, employee: Employee, on_date: date) -> list[P.DeductionLine]:
    rows = db.scalars(
        select(EmployeeDeduction).where(
            EmployeeDeduction.employee_id == employee.id,
            EmployeeDeduction.is_active.is_(True),
            EmployeeDeduction.effective_from <= on_date,
        )
    ).all()
    lines: list[P.DeductionLine] = []
    for r in rows:
        if r.effective_to is not None and r.effective_to < on_date:
            continue
        dt = db.scalar(select(DeductionType).where(DeductionType.id == r.deduction_type_id))
        if dt is None:
            raise AppError(
                "deduction_type_missing",
                f"employee_deduction {r.id} references missing deduction_type",
                500,
            )
        lines.append(P.DeductionLine(
            label=dt.name,
            amount=Decimal(r.amount),
            category=dt.category,
            is_pre_tax=bool(dt.is_pre_tax),
            priority=dt.priority,
            source_ref={"employee_deduction_id": str(r.id), "deduction_type_code": dt.code},
        ))
    return lines


# ---------------------------------------------------------------------------
# Payslip writing
# ---------------------------------------------------------------------------

def _write_payslip(
    db: Session, run: PayrollRun, pay_period: PayPeriod,
    employee: Employee, draft: P.PayslipDraft, *, status: str,
    prior: Payslip | None,
) -> Payslip:
    payslip = Payslip(
        id=uuid.uuid4(),
        payroll_run_id=run.id,
        pay_period_id=pay_period.id,
        employee_id=employee.id,
        revision=run.revision,
        status=status,
        gross=draft.gross,
        pre_tax_deductions=draft.pre_tax_deductions,
        taxable_income=draft.taxable_income,
        paye=draft.paye,
        uif_employee=draft.uif_employee,
        uif_employer=draft.uif_employer,
        sdl=draft.sdl,
        other_deductions=draft.other_deductions,
        reimbursements=draft.reimbursements,
        net=draft.net,
        employer_costs=draft.employer_costs(),
        snapshot={"calculation_context": draft.calculation_context, "tax_trace": draft.tax_trace},
        calculation_context=draft.calculation_context,
        predecessor_payslip_id=prior.id if prior else None,
    )
    db.add(payslip)
    db.flush()

    if prior is not None and prior.status == "current" and status == "current":
        prior.status = "superseded"

    # Lines: 1 per earning/deduction + 1 per stat + 1 reimbursement bucket
    sort = 0
    for i, d in enumerate(draft.deferred_deductions):
        sort += 1
        db.add(PayslipLine(
            id=uuid.uuid4(), payslip_id=payslip.id,
            line_type="deduction", step="other", sort_order=1000 + i,
            label=f"Deferred: {d['label']}",
            amount=Decimal(d["amount"]),
            source_ref={"deferred": True, "category": d.get("category")},
        ))
    db.add(PayslipLine(
        id=uuid.uuid4(), payslip_id=payslip.id,
        line_type="tax", step="tax", sort_order=200, label="PAYE",
        amount=draft.paye, source_ref={"method": draft.calculation_context.get("tax_method")},
    ))
    db.add(PayslipLine(
        id=uuid.uuid4(), payslip_id=payslip.id,
        line_type="deduction", step="statutory", sort_order=300, label="UIF (employee)",
        amount=draft.uif_employee, source_ref={"statutory": "uif"},
    ))
    db.add(PayslipLine(
        id=uuid.uuid4(), payslip_id=payslip.id,
        line_type="employer_cost", step="employer_cost", sort_order=800,
        label="UIF (employer)", amount=draft.uif_employer,
        source_ref={"statutory": "uif"},
    ))
    db.add(PayslipLine(
        id=uuid.uuid4(), payslip_id=payslip.id,
        line_type="employer_cost", step="employer_cost", sort_order=810,
        label="SDL", amount=draft.sdl, source_ref={"statutory": "sdl"},
    ))
    db.flush()
    return payslip


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

def _purge_preview(db: Session, pay_period_id: uuid.UUID) -> None:
    prior = db.scalar(
        select(PayrollRun).where(
            PayrollRun.pay_period_id == pay_period_id,
            PayrollRun.kind == "preview",
        ).order_by(PayrollRun.started_at.desc())
    )
    if prior is None:
        return
    db.execute(
        PayslipLine.__table__.delete().where(
            PayslipLine.payslip_id.in_(
                select(Payslip.id).where(Payslip.payroll_run_id == prior.id)
            )
        )
    )
    db.execute(Payslip.__table__.delete().where(Payslip.payroll_run_id == prior.id))
    db.execute(PayrollRun.__table__.delete().where(PayrollRun.id == prior.id))
    db.flush()


def _in_scope_employees(db: Session) -> list[Employee]:
    return list(db.scalars(
        select(Employee).where(Employee.status != "terminated")
    ).all())


def _formula_warnings(db: Session) -> list[str]:
    settings = _load_settings(db)
    acks = settings.formula_acks or {}
    return [code for code in FORMULA_REGISTRY if code not in acks]


def run_preview(db: Session, user, pay_period: PayPeriod) -> PayrollRun:
    if pay_period.status == "locked":
        raise AppError("period_locked", "Cannot preview a finalised period; reopen it first", 409)

    _purge_preview(db, pay_period.id)
    ensure_system_earning_types(db)

    # Determine next revision for preview (each preview gets fresh rev)
    prior_final_max = db.scalar(
        select(Payslip.revision).where(Payslip.pay_period_id == pay_period.id)
        .order_by(Payslip.revision.desc())
    ) or 0
    rev = int(prior_final_max) + 1

    run = PayrollRun(
        id=uuid.uuid4(),
        pay_period_id=pay_period.id,
        kind="preview",
        revision=rev,
        status="running",
        rules_snapshot={},  # filled below
        started_by_user_id=getattr(user, "id", None),
    )
    db.add(run)
    db.flush()

    warnings = _formula_warnings(db)
    run.rules_snapshot = {
        "preview": True,
        "unacknowledged_formulas": warnings,
        "employee_count": 0,
    }

    employees = _in_scope_employees(db)
    for emp in employees:
        config = build_pipeline_config(db, emp, pay_period.pay_date)
        earnings = _build_earnings(db, emp, pay_period.pay_date)
        deductions = _build_deductions(db, emp, pay_period.pay_date)
        draft = P.run_pipeline(config, earnings, deductions, [])
        if draft.refused:
            run.status = "failed"
            run.error_code = draft.refusal_code
            run.error_detail = f"employee {emp.employee_code}: {draft.refusal_message}"
            run.completed_at = datetime.now(timezone.utc)
            db.flush()
            raise AppError(draft.refusal_code or "compute_refused", draft.refusal_message or "", 409)
        _write_payslip(db, run, pay_period, emp, draft, status="preview", prior=None)
        run.rules_snapshot["employee_count"] = run.rules_snapshot["employee_count"] + 1

    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    db.flush()
    write_audit(
        db, user,
        entity_type="payroll_run", entity_id=run.id, action="preview",
        new_value={"pay_period_id": str(pay_period.id), "employee_count": run.rules_snapshot["employee_count"]},
    )
    return run


# ---------------------------------------------------------------------------
# Finalise
# ---------------------------------------------------------------------------

def finalise(db: Session, user, pay_period: PayPeriod) -> PayrollRun:
    if pay_period.status == "locked":
        raise AppError("period_locked", "Period is already finalised", 409)

    warnings = _formula_warnings(db)
    if warnings:
        raise AppError(
            "formula_unacknowledged",
            f"cannot finalise until all formulas are acknowledged; missing: {warnings}",
            409,
        )

    _purge_preview(db, pay_period.id)
    ensure_system_earning_types(db)

    prior_final_max = db.scalar(
        select(Payslip.revision).where(Payslip.pay_period_id == pay_period.id)
        .order_by(Payslip.revision.desc())
    ) or 0
    rev = int(prior_final_max) + 1

    run = PayrollRun(
        id=uuid.uuid4(),
        pay_period_id=pay_period.id,
        kind="final",
        revision=rev,
        status="running",
        rules_snapshot={},
        started_by_user_id=getattr(user, "id", None),
    )
    db.add(run)
    db.flush()

    employees = _in_scope_employees(db)
    run.rules_snapshot = {"final": True, "employee_count": 0, "revision": rev}

    for emp in employees:
        prior = db.scalar(
            select(Payslip).where(
                Payslip.pay_period_id == pay_period.id,
                Payslip.employee_id == emp.id,
                Payslip.status == "current",
            )
        )
        config = build_pipeline_config(db, emp, pay_period.pay_date)
        earnings = _build_earnings(db, emp, pay_period.pay_date)
        deductions = _build_deductions(db, emp, pay_period.pay_date)
        draft = P.run_pipeline(config, earnings, deductions, [])
        if draft.refused:
            run.status = "failed"
            run.error_code = draft.refusal_code
            run.error_detail = f"employee {emp.employee_code}: {draft.refusal_message}"
            run.completed_at = datetime.now(timezone.utc)
            db.flush()
            raise AppError(draft.refusal_code or "compute_refused", draft.refusal_message or "", 409)
        _write_payslip(db, run, pay_period, emp, draft, status="current", prior=prior)
        run.rules_snapshot["employee_count"] = run.rules_snapshot["employee_count"] + 1

    pay_period.status = "locked"
    pay_period.row_version += 1
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    db.flush()
    write_audit(
        db, user,
        entity_type="payroll_run", entity_id=run.id, action="finalise",
        new_value={"pay_period_id": str(pay_period.id), "revision": rev,
                   "employee_count": run.rules_snapshot["employee_count"]},
    )
    return run


# ---------------------------------------------------------------------------
# Reopen
# ---------------------------------------------------------------------------

def reopen(db: Session, user, pay_period: PayPeriod, reason: str) -> PeriodReopenLog:
    if pay_period.status != "locked":
        raise AppError("period_not_locked", "Only a locked period can be reopened", 409)

    # E9(a): only the most recent finalised period may be reopened, or later
    # ones reopened first
    later_locked = db.scalar(
        select(PayPeriod).where(
            PayPeriod.status == "locked",
            PayPeriod.pay_date > pay_period.pay_date,
        ).limit(1)
    )
    if later_locked is not None:
        raise AppError(
            "later_period_locked",
            f"reopen later locked period {later_locked.period_key!r} first",
            409,
        )

    prior_rev = db.scalar(
        select(Payslip.revision).where(Payslip.pay_period_id == pay_period.id)
        .order_by(Payslip.revision.desc())
    ) or 0
    new_rev = int(prior_rev) + 1

    log = PeriodReopenLog(
        id=uuid.uuid4(),
        pay_period_id=pay_period.id,
        reopened_by_user_id=getattr(user, "id", None),
        reason=reason,
        prior_revision=int(prior_rev),
        new_revision=new_rev,
    )
    db.add(log)
    pay_period.status = "open"
    pay_period.row_version += 1
    db.flush()
    write_audit(
        db, user,
        entity_type="pay_period", entity_id=pay_period.id, action="reopen",
        old_value={"status": "locked"}, new_value={"status": "open", "reason": reason},
    )
    return log

# END OF FILE
