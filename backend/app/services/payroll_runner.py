"""Payroll runner (Chapter 4 Bundle 004b-a + Chapter 4H B-4c/d/e + B-3).

B-3 additions: `_write_payslip` now persists one `PayslipLine` per
`EarningLine` and per `DeductionLine` so `GET /payroll/pay-periods/{id}/
preview/{employee_id}` can surface the actual line detail without
recomputing.

M6 Part 2 Stage 1: `run_preview`, `finalise` and `reopen` now take a
`SELECT ... FOR UPDATE` on `pay_period` at the top of the function so
concurrent calls serialize.

M6 Part 2 Stage 2: `_cr_could_affect_locked_periods` supports the CR-
approval guard in `payroll_change_request._apply`. Effective-window overlap
with existing-row window included for update/deactivate kinds; field updates
block on any locked payslip.

M6 Part 2 Stage 3: `finalise` refuses with 409 `pending_change_requests_in_period`
when any pending change request could affect the period if approved.

M6 Part 2 Stage 4: `run_preview` stores a canonical `input_hash` in
`PayrollRun.rules_snapshot`. `finalise` recomputes it and, if a preview run
exists with a different hash, refuses with 409 `preview_stale` unless
`ack_stale_preview_reason` is provided. This closes the residual race where
inputs change between preview and finalise but the pending-CR gate cannot
see them (approved CRs, direct employee edits, etc.).

M6 Part 2 Stage 5 (F22): `run_preview_for_employee_as_of` now reads
`deduction_type_code` from `DeductionLine.source_ref`.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tenant.models.attendance import (
    AttendanceDay,
    AttendanceSegment,
    ExceptionItem,
    Shift,
)
from app.db.tenant.models.pay import (
    EarningType, EmployeeEarning, EmployeeDeduction, DeductionType,
    PayPeriod, PayrollRun, Payslip, PayslipLine, PeriodReopenLog,
)
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.people import (
    Employee, EmployeePayHistory,
)
from app.services import payroll_pipeline as P
from app.services import payroll_refusals as R
from app.services import payroll_tax as T
from app.services.payroll_audit import write_audit
from app.services.payroll_formulas import (
    DERIVATION_FORMULAS,
    FORMULA_REGISTRY,
    gen_paid_leave,
    gen_unpaid_absence,
    hourly_rate_from_monthly,
)
from app.services.payroll_seed import ensure_system_earning_types
from app.services.statutory_loader import (
    _default_engine, _ensure_bootstrapped, get_active_table,
)


_COUNTRY_CODE = "ZA"
_PERIODS_PER_YEAR = {"monthly": 12, "weekly": 52, "fortnightly": 26}

_UNPAID_DAY_FORMULAS = {
    "gen_unpaid_absence": gen_unpaid_absence,
}


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
    _ensure_bootstrapped(engine)
    row = get_active_table(engine, _COUNTRY_CODE, table_type, on_date)
    if row is None:
        raise AppError(
            "statutory_table_missing",
            f"{_COUNTRY_CODE}/{table_type} has no active version covering {on_date.isoformat()}",
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

    age_date = pay_date
    age = _resolve_age(employee, age_date, settings.age_reference_date)

    control_engine = _default_engine()
    _ensure_bootstrapped(control_engine)
    try:
        tax_tables = T.load_tax_tables(control_engine, pay_date, country_code=_COUNTRY_CODE)
    except R.PayrollRefusal as exc:
        raise AppError(exc.code, exc.message, exc.http_status) from None

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


def _build_fixed_earnings(
    db: Session, employee: Employee, on_date: date,
) -> list[P.EarningLine]:
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
                f"use ensure-system or a fixed_amount earning_type for direct "
                f"employee_earning rows",
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


def _rate_in_force_for(
    db: Session,
    employee: Employee,
    on_date: date,
    settings: PayrollSettings,
    warnings: list[str],
) -> Decimal:
    if employee.pay_basis == "hourly" or employee.pay_basis == "daily":
        ph = db.scalar(
            select(EmployeePayHistory).where(
                EmployeePayHistory.employee_id == employee.id,
                EmployeePayHistory.status == "approved",
                EmployeePayHistory.effective_from <= on_date,
            ).order_by(
                EmployeePayHistory.effective_from.desc(),
                EmployeePayHistory.created_at.desc(),
                EmployeePayHistory.id.desc(),
            ).limit(1)
        )
        if ph is not None:
            return Decimal(ph.base_rate)
        if employee.base_rate is not None:
            warnings.append(
                f"rate_history_missing:{employee.employee_code}:"
                f"{on_date.isoformat()}:using_current_base_rate"
            )
            return Decimal(employee.base_rate)
        raise AppError(
            "missing_base_rate",
            f"employee {employee.employee_code} has no approved pay history "
            f"and no base_rate; cannot compute hourly amount",
            409,
        )

    code = settings.monthly_hourly_derivation_formula_code
    if code is None:
        raise AppError(
            "monthly_hourly_derivation_not_configured",
            f"employee {employee.employee_code} is monthly-paid; hourly rate "
            f"is needed here but payroll.monthly_hourly_derivation_formula_code "
            f"is unset",
            409,
            {"employee_code": employee.employee_code},
        )
    if code not in DERIVATION_FORMULAS:
        raise AppError(
            "monthly_hourly_derivation_unknown",
            f"monthly_hourly_derivation_formula_code={code!r} is not in "
            f"DERIVATION_FORMULAS={sorted(DERIVATION_FORMULAS)}",
            409,
        )
    if employee.contracted_weekly_hours is None:
        raise AppError(
            "missing_contracted_hours",
            f"employee {employee.employee_code} is monthly-paid but has no "
            f"contracted_weekly_hours; cannot derive hourly rate",
            409,
        )
    monthly_salary = _monthly_salary_from_earnings(db, employee, on_date)
    if monthly_salary is None:
        raise AppError(
            "monthly_salary_not_configured",
            f"employee {employee.employee_code} has no BASE_MONTHLY earning "
            f"effective on {on_date.isoformat()}; cannot derive hourly rate",
            409,
        )
    return hourly_rate_from_monthly(
        monthly_salary=monthly_salary,
        contracted_weekly_hours=Decimal(employee.contracted_weekly_hours),
    )


def _monthly_salary_from_earnings(
    db: Session, employee: Employee, on_date: date,
) -> Decimal | None:
    et = db.scalar(select(EarningType).where(EarningType.code == "BASE_MONTHLY"))
    if et is None:
        return None
    row = db.scalar(
        select(EmployeeEarning).where(
            EmployeeEarning.employee_id == employee.id,
            EmployeeEarning.earning_type_id == et.id,
            EmployeeEarning.is_active.is_(True),
            EmployeeEarning.effective_from <= on_date,
        ).order_by(EmployeeEarning.effective_from.desc()).limit(1)
    )
    if row is None or row.amount is None:
        return None
    if row.effective_to is not None and row.effective_to < on_date:
        return None
    return Decimal(row.amount)


def _daily_rate_for_employee_on_date(
    db: Session,
    employee: Employee,
    on_date: date,
    settings: PayrollSettings,
    warnings: list[str],
) -> Decimal:
    rate = _rate_in_force_for(db, employee, on_date, settings, warnings)
    if employee.default_shift_id is not None:
        shift = db.get(Shift, employee.default_shift_id)
        if shift is not None:
            return rate * (Decimal(shift.length_minutes) / Decimal(60))
    if employee.contracted_weekly_hours is not None:
        return rate * (Decimal(employee.contracted_weekly_hours) / Decimal(5))
    raise AppError(
        "daily_rate_unavailable",
        f"cannot compute daily rate for {employee.employee_code}: no default "
        f"shift and no contracted_weekly_hours",
        409,
    )


def _group_key_for_segment(seg: AttendanceSegment) -> str:
    tier_part = str(seg.tier) if seg.kind == "overtime" else "any"
    return f"{seg.kind}|{seg.day_type}|{tier_part}"


def _segment_amount(seg: AttendanceSegment, rate: Decimal) -> Decimal:
    if seg.rate_method == "multiplier":
        per_hour = rate * Decimal(seg.rate_value)
        return (Decimal(seg.minutes) / Decimal(60) * per_hour).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP,
        )
    if seg.rate_method == "flat":
        raise AppError(
            "flat_rate_unsupported",
            f"attendance segment id={seg.id} has rate_method='flat'; a "
            f"flat-allowance divisor is not yet configured (round-2 "
            f"amendment 3 keeps invented divisors out of code). Use "
            f"rate_method='multiplier' on the shift_rate_rule, or wait for a "
            f"future allowance policy setting.",
            409,
        )
    raise AppError(
        "unknown_rate_method",
        f"attendance segment id={seg.id} has unknown rate_method="
        f"{seg.rate_method!r}",
        409,
    )


def _build_attendance_earnings(
    db: Session,
    employee: Employee,
    pay_period: PayPeriod,
    through_date: date | None = None,
) -> tuple[list[P.EarningLine], list[str], dict]:
    settings = _load_settings(db)
    warnings: list[str] = []
    snapshot: dict = {
        "grouped_minutes": {},
        "mapping_used": {},
        "rates_by_date": {},
        "settings": {
            "unpaid_day_behaviour": settings.unpaid_day_behaviour,
            "unpaid_day_formula_code": settings.unpaid_day_formula_code,
            "public_holiday_unworked_monthly": settings.public_holiday_unworked_monthly,
            "public_holiday_paid": settings.public_holiday_paid,
            "leave_authoritative_source": settings.leave_authoritative_source,
            "monthly_hourly_derivation_formula_code":
                settings.monthly_hourly_derivation_formula_code,
            "attendance_earning_map": dict(settings.attendance_earning_map or {}),
            "demo_values": bool(settings.demo_values),
        },
    }
    lines: list[P.EarningLine] = []

    if settings.leave_authoritative_source in ("leave_request", "both"):
        raise AppError(
            "leave_source_not_available",
            f"leave_authoritative_source={settings.leave_authoritative_source!r} "
            f"is not supported until Chapter 3 leave services land; only "
            f"'adjustment' is available",
            422,
            {"leave_authoritative_source": settings.leave_authoritative_source},
        )

    days = list(db.scalars(
        select(AttendanceDay).where(
            AttendanceDay.employee_id == employee.id,
            AttendanceDay.work_date >= pay_period.start_date,
            AttendanceDay.work_date <= pay_period.end_date,
        )
    ).all())
    if through_date is not None:
        days = [d for d in days if d.work_date <= through_date]
    if not days:
        return [], warnings, snapshot

    day_by_id = {d.id: d for d in days}
    segments = list(db.scalars(
        select(AttendanceSegment).where(
            AttendanceSegment.attendance_day_id.in_(list(day_by_id.keys()))
        )
    ).all())

    grouped: dict[str, int] = {}
    for seg in segments:
        if seg.minutes <= 0:
            continue
        key = _group_key_for_segment(seg)
        grouped[key] = grouped.get(key, 0) + int(seg.minutes)
    snapshot["grouped_minutes"] = dict(grouped)

    mapping = settings.attendance_earning_map or {}
    missing_keys = [k for k in grouped.keys() if k not in mapping]
    if missing_keys:
        raise AppError(
            "attendance_earning_map_incomplete",
            f"attendance_earning_map is missing keys: {sorted(missing_keys)}; "
            f"set them via PATCH /payroll/settings before previewing",
            409,
            {"missing_keys": sorted(missing_keys)},
        )
    snapshot["mapping_used"] = {k: mapping[k] for k in grouped.keys()}

    type_codes = {mapping[k] for k in grouped.keys()}
    types_by_code = {t.code: t for t in db.scalars(
        select(EarningType).where(EarningType.code.in_(type_codes))
    ).all()}
    missing_types = type_codes - set(types_by_code.keys())
    if missing_types:
        raise AppError(
            "attendance_earning_type_missing",
            f"earning types referenced by attendance_earning_map are missing: "
            f"{sorted(missing_types)}; call POST /payroll/earning-types/ensure-system",
            409,
            {"missing_types": sorted(missing_types)},
        )

    agg: dict[str, dict] = {}
    for seg in segments:
        if seg.minutes <= 0:
            continue
        day = day_by_id.get(seg.attendance_day_id)
        if day is None:
            continue
        if employee.pay_basis == "monthly" and seg.kind == "normal":
            continue

        key = _group_key_for_segment(seg)
        code = mapping[key]
        et = types_by_code[code]

        if seg.kind == "overtime":
            shift = db.get(Shift, day.shift_id) if day.shift_id else None
            requires_approval = bool(shift and shift.overtime_requires_approval)
            if requires_approval and seg.overtime_status != "approved":
                warnings.append(
                    f"overtime_unapproved:{employee.employee_code}:"
                    f"{day.work_date.isoformat()}:{seg.minutes}min"
                )
                continue

        rate = _rate_in_force_for(db, employee, seg.local_date, settings, warnings)
        snapshot["rates_by_date"][seg.local_date.isoformat()] = str(rate)

        amount = _segment_amount(seg, rate)
        bucket = agg.setdefault(code, {
            "minutes": 0,
            "amount": Decimal("0.0000"),
            "count": 0,
            "label": et.name,
            "frequency": et.frequency,
            "is_taxable": bool(et.is_taxable),
            "counts_for_uif": bool(et.counts_for_uif),
            "counts_for_sdl": bool(et.counts_for_sdl),
        })
        bucket["minutes"] += int(seg.minutes)
        bucket["amount"] += amount
        bucket["count"] += 1

    for code, b in agg.items():
        lines.append(P.EarningLine(
            label=f"{b['label']} ({b['minutes']} min)",
            amount=b["amount"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            frequency=b["frequency"],
            is_taxable=b["is_taxable"],
            counts_for_uif=b["counts_for_uif"],
            counts_for_sdl=b["counts_for_sdl"],
            source_ref={
                "attendance_derived": True,
                "earning_type_code": code,
                "minutes": b["minutes"],
                "segment_count": b["count"],
            },
        ))

    absent_days = [
        d for d in days
        if d.status == "absent" and (d.worked_minutes or 0) == 0
    ]
    if absent_days:
        if settings.unpaid_day_behaviour is None:
            raise AppError(
                "unpaid_day_behaviour_not_configured",
                f"payroll.unpaid_day_behaviour is unset but "
                f"{len(absent_days)} absent day(s) exist in the period",
                409,
            )
        if settings.unpaid_day_behaviour == "skip":
            pass
        elif settings.unpaid_day_behaviour == "deduct_daily":
            if employee.pay_basis != "monthly":
                warnings.append(
                    f"unpaid_day_hourly_not_deducted:{employee.employee_code}:"
                    f"{len(absent_days)}day(s)"
                )
            else:
                formula_code = settings.unpaid_day_formula_code
                if formula_code is None:
                    raise AppError(
                        "unpaid_day_formula_code_not_configured",
                        "unpaid_day_behaviour='deduct_daily' requires "
                        "unpaid_day_formula_code",
                        409,
                    )
                fn = _UNPAID_DAY_FORMULAS.get(formula_code)
                if fn is None:
                    raise AppError(
                        "unpaid_day_formula_unsupported",
                        f"unpaid_day_formula_code={formula_code!r} cannot "
                        f"compute an unpaid-day amount; supported: "
                        f"{sorted(_UNPAID_DAY_FORMULAS)}",
                        409,
                    )
                daily_rate = _daily_rate_for_employee_on_date(
                    db, employee, pay_period.pay_date, settings, warnings,
                )
                positive = fn(
                    daily_rate=daily_rate,
                    unpaid_days=Decimal(len(absent_days)),
                )
                lines.append(P.EarningLine(
                    label=f"Unpaid absence ({len(absent_days)} day(s))",
                    amount=-positive,
                    frequency="regular",
                    is_taxable=True,
                    counts_for_uif=True,
                    counts_for_sdl=True,
                    source_ref={
                        "attendance_derived": True,
                        "kind": "unpaid_day",
                        "formula_code": formula_code,
                        "absent_count": len(absent_days),
                    },
                ))
        elif settings.unpaid_day_behaviour == "deduct_hourly":
            raise AppError(
                "unpaid_day_behaviour_not_supported",
                "unpaid_day_behaviour='deduct_hourly' is not supported; use "
                "'deduct_daily' with an accountant-acknowledged formula code",
                409,
            )
        else:
            raise AppError(
                "unpaid_day_behaviour_invalid",
                f"unpaid_day_behaviour={settings.unpaid_day_behaviour!r} unknown",
                409,
            )

    unworked_ph = [d for d in days if d.status == "public_holiday_unworked"]
    if unworked_ph:
        beh = settings.public_holiday_unworked_monthly
        if beh is None:
            raise AppError(
                "public_holiday_behaviour_not_configured",
                f"payroll.public_holiday_unworked_monthly is unset but "
                f"{len(unworked_ph)} unworked public-holiday day(s) exist",
                409,
            )
        if beh == "settings_per_day_type":
            if settings.public_holiday_paid is None:
                raise AppError(
                    "public_holiday_paid_unset",
                    "public_holiday_unworked_monthly='settings_per_day_type' "
                    "requires public_holiday_paid to be set (true/false)",
                    409,
                )
            beh = "paid" if settings.public_holiday_paid else "unpaid"
        if beh == "paid":
            pass
        elif beh == "unpaid":
            if employee.pay_basis != "monthly":
                warnings.append(
                    f"public_holiday_unpaid_hourly:{employee.employee_code}:"
                    f"{len(unworked_ph)}day(s)"
                )
            else:
                formula_code = settings.unpaid_day_formula_code
                if formula_code is None:
                    raise AppError(
                        "public_holiday_formula_code_not_configured",
                        "public_holiday_unworked_monthly='unpaid' requires "
                        "unpaid_day_formula_code",
                        409,
                    )
                fn = _UNPAID_DAY_FORMULAS.get(formula_code)
                if fn is None:
                    raise AppError(
                        "public_holiday_formula_unsupported",
                        f"unpaid_day_formula_code={formula_code!r} cannot "
                        f"compute a public-holiday amount",
                        409,
                    )
                daily_rate = _daily_rate_for_employee_on_date(
                    db, employee, pay_period.pay_date, settings, warnings,
                )
                positive = fn(
                    daily_rate=daily_rate,
                    unpaid_days=Decimal(len(unworked_ph)),
                )
                lines.append(P.EarningLine(
                    label=f"Unworked public holiday ({len(unworked_ph)} day(s))",
                    amount=-positive,
                    frequency="regular",
                    is_taxable=True,
                    counts_for_uif=True,
                    counts_for_sdl=True,
                    source_ref={
                        "attendance_derived": True,
                        "kind": "public_holiday_unpaid",
                        "formula_code": formula_code,
                        "day_count": len(unworked_ph),
                    },
                ))
        else:
            raise AppError(
                "public_holiday_behaviour_invalid",
                f"public_holiday_unworked_monthly={beh!r} unknown",
                409,
            )

    leave_days = [d for d in days if d.status == "leave"]
    if leave_days:
        if settings.leave_authoritative_source is None:
            raise AppError(
                "leave_source_not_configured",
                "payroll.leave_authoritative_source is unset but "
                f"{len(leave_days)} leave day(s) exist in the period",
                409,
            )
        if employee.pay_basis == "monthly" and not bool(settings.leave_earning_for_monthly):
            pass
        else:
            daily_rate = _daily_rate_for_employee_on_date(
                db, employee, pay_period.pay_date, settings, warnings,
            )
            amount = gen_paid_leave(
                daily_rate=daily_rate,
                paid_leave_days=Decimal(len(leave_days)),
            )
            lines.append(P.EarningLine(
                label=f"Paid leave ({len(leave_days)} day(s))",
                amount=amount,
                frequency="regular",
                is_taxable=True,
                counts_for_uif=True,
                counts_for_sdl=True,
                source_ref={
                    "attendance_derived": True,
                    "kind": "paid_leave",
                    "day_count": len(leave_days),
                },
            ))

    return lines, warnings, snapshot


def _build_all_earnings(
    db: Session, employee: Employee, pay_period: PayPeriod,
    through_date: date | None = None,
) -> tuple[list[P.EarningLine], list[str], dict]:
    fixed = _build_fixed_earnings(db, employee, pay_period.pay_date)
    attn, warnings, snapshot = _build_attendance_earnings(
        db, employee, pay_period, through_date=through_date,
    )
    return fixed + attn, warnings, snapshot


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


def _write_payslip(
    db: Session, run: PayrollRun, pay_period: PayPeriod,
    employee: Employee, draft: P.PayslipDraft, *,
    earnings: list[P.EarningLine],
    deductions: list[P.DeductionLine],
    status: str,
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

    # B-3: persist each earning and deduction as a PayslipLine for
    # GET .../preview/{employee_id}. Persisted amount matches the pipeline's
    # contribution to gross / other_deductions.
    for i, e in enumerate(earnings):
        src = dict(e.source_ref or {})
        if "attendance_derived" in src:
            src["rate_source"] = "attendance"
        else:
            src["rate_source"] = "employee_earning"
        src.setdefault("amount", str(e.amount))
        db.add(PayslipLine(
            id=uuid.uuid4(), payslip_id=payslip.id,
            line_type="earning", step="gross", sort_order=i,
            label=e.label, amount=e.amount, source_ref=src,
        ))
    for i, d in enumerate(deductions):
        src = dict(d.source_ref or {})
        src.setdefault("amount", str(d.amount))
        db.add(PayslipLine(
            id=uuid.uuid4(), payslip_id=payslip.id,
            line_type="deduction",
            step="pre_tax" if d.is_pre_tax else "other",
            sort_order=500 + i,
            label=d.label, amount=d.amount, source_ref=src,
        ))
    for i, d in enumerate(draft.deferred_deductions):
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


def _count_open_exceptions_in_period(
    db: Session, pay_period: PayPeriod,
) -> tuple[int, list[dict]]:
    rows = db.execute(
        select(
            ExceptionItem.employee_id,
            ExceptionItem.work_date,
            ExceptionItem.type,
        ).where(
            ExceptionItem.work_date >= pay_period.start_date,
            ExceptionItem.work_date <= pay_period.end_date,
            ExceptionItem.status == "open",
        ).limit(1000)
    ).all()
    count = len(rows)
    sample = [
        {"employee_id": str(r[0]), "work_date": r[1].isoformat(), "type": r[2]}
        for r in rows[:5]
    ]
    return count, sample


# ---------------------------------------------------------------------------
# M6 Part 2 Stage 4 — canonical input hash for preview/finalise comparison
#
# The hash captures only the fields the calc pipeline actually reads. It
# does NOT include:
#   - exceptions (gate-only, not calc inputs)
#   - formula_acks (gate-only)
#   - cosmetic fields (labels, names, email, mobile)
#   - statutory tables in the control DB (controlled release; re-preview
#     is the operational answer if they update)
#
# Deterministic by construction: rows sorted by id, dicts sorted by key,
# Decimals rendered via their DB-consistent string form, dates via
# isoformat.
# ---------------------------------------------------------------------------


def _json_default(o):
    if isinstance(o, Decimal):
        return format(o, "f")
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, uuid.UUID):
        return str(o)
    raise TypeError(f"unhashable type in input snapshot: {type(o).__name__}")


def _build_input_snapshot(db: Session, pay_period: PayPeriod) -> dict:
    employees = list(db.scalars(
        select(Employee).where(Employee.status != "terminated")
    ).all())
    employees.sort(key=lambda e: str(e.id))
    emp_ids = [e.id for e in employees]

    employee_data = [
        {
            "id": str(e.id),
            "status": e.status,
            "pay_basis": e.pay_basis,
            "pay_frequency": e.pay_frequency,
            "base_rate": str(e.base_rate) if e.base_rate is not None else None,
            "uif_exempt": bool(e.uif_exempt),
            "medical_scheme_members": int(e.medical_scheme_members or 0),
            "contracted_weekly_hours": (
                str(e.contracted_weekly_hours)
                if e.contracted_weekly_hours is not None else None
            ),
            "date_of_birth": e.date_of_birth.isoformat() if e.date_of_birth else None,
            "default_shift_id": (
                str(e.default_shift_id) if e.default_shift_id else None
            ),
        }
        for e in employees
    ]

    earnings = list(db.scalars(
        select(EmployeeEarning).where(EmployeeEarning.employee_id.in_(emp_ids))
    ).all()) if emp_ids else []
    earnings.sort(key=lambda r: str(r.id))
    earnings_data = [
        {
            "id": str(r.id),
            "employee_id": str(r.employee_id),
            "earning_type_id": str(r.earning_type_id),
            "amount": str(r.amount) if r.amount is not None else None,
            "rate": str(r.rate) if r.rate is not None else None,
            "effective_from": r.effective_from.isoformat(),
            "effective_to": r.effective_to.isoformat() if r.effective_to else None,
            "is_active": bool(r.is_active),
        }
        for r in earnings
    ]

    earning_type_ids = {r.earning_type_id for r in earnings}
    earning_types = list(db.scalars(
        select(EarningType).where(EarningType.id.in_(earning_type_ids))
    ).all()) if earning_type_ids else []
    earning_types.sort(key=lambda t: str(t.id))
    earning_types_data = [
        {
            "id": str(t.id),
            "code": t.code,
            "calc_method": t.calc_method,
            "frequency": t.frequency,
            "is_taxable": bool(t.is_taxable),
            "counts_for_uif": bool(t.counts_for_uif),
            "counts_for_sdl": bool(t.counts_for_sdl),
        }
        for t in earning_types
    ]

    deductions = list(db.scalars(
        select(EmployeeDeduction).where(EmployeeDeduction.employee_id.in_(emp_ids))
    ).all()) if emp_ids else []
    deductions.sort(key=lambda r: str(r.id))
    deductions_data = [
        {
            "id": str(r.id),
            "employee_id": str(r.employee_id),
            "deduction_type_id": str(r.deduction_type_id),
            "amount": str(r.amount),
            "effective_from": r.effective_from.isoformat(),
            "effective_to": r.effective_to.isoformat() if r.effective_to else None,
            "is_active": bool(r.is_active),
        }
        for r in deductions
    ]

    deduction_type_ids = {r.deduction_type_id for r in deductions}
    deduction_types = list(db.scalars(
        select(DeductionType).where(DeductionType.id.in_(deduction_type_ids))
    ).all()) if deduction_type_ids else []
    deduction_types.sort(key=lambda t: str(t.id))
    deduction_types_data = [
        {
            "id": str(t.id),
            "code": t.code,
            "category": t.category,
            "is_pre_tax": bool(t.is_pre_tax),
            "priority": int(t.priority),
        }
        for t in deduction_types
    ]

    history = list(db.scalars(
        select(EmployeePayHistory).where(
            EmployeePayHistory.employee_id.in_(emp_ids),
            EmployeePayHistory.status == "approved",
        )
    ).all()) if emp_ids else []
    history.sort(key=lambda h: str(h.id))
    history_data = [
        {
            "id": str(h.id),
            "employee_id": str(h.employee_id),
            "base_rate": str(h.base_rate),
            "effective_from": h.effective_from.isoformat(),
        }
        for h in history
    ]

    days = list(db.scalars(
        select(AttendanceDay).where(
            AttendanceDay.employee_id.in_(emp_ids),
            AttendanceDay.work_date >= pay_period.start_date,
            AttendanceDay.work_date <= pay_period.end_date,
        )
    ).all()) if emp_ids else []
    days.sort(key=lambda d: str(d.id))
    days_data = [
        {
            "id": str(d.id),
            "employee_id": str(d.employee_id),
            "work_date": d.work_date.isoformat(),
            "status": d.status,
            "worked_minutes": int(d.worked_minutes or 0),
            "shift_id": str(d.shift_id) if d.shift_id else None,
        }
        for d in days
    ]

    day_ids = [d.id for d in days]
    segments = list(db.scalars(
        select(AttendanceSegment).where(
            AttendanceSegment.attendance_day_id.in_(day_ids)
        )
    ).all()) if day_ids else []
    segments.sort(key=lambda s: str(s.id))
    segments_data = [
        {
            "id": str(s.id),
            "attendance_day_id": str(s.attendance_day_id),
            "kind": s.kind,
            "day_type": s.day_type,
            "tier": str(s.tier) if s.tier is not None else None,
            "minutes": int(s.minutes),
            "rate_method": s.rate_method,
            "rate_value": str(s.rate_value) if s.rate_value is not None else None,
            "overtime_status": s.overtime_status,
            "local_date": s.local_date.isoformat(),
        }
        for s in segments
    ]

    shift_ids = set()
    for e in employees:
        if e.default_shift_id is not None:
            shift_ids.add(e.default_shift_id)
    for d in days:
        if d.shift_id is not None:
            shift_ids.add(d.shift_id)
    shifts = list(db.scalars(
        select(Shift).where(Shift.id.in_(shift_ids))
    ).all()) if shift_ids else []
    shifts.sort(key=lambda s: str(s.id))
    shifts_data = [
        {
            "id": str(s.id),
            "length_minutes": int(s.length_minutes) if s.length_minutes is not None else None,
            "overtime_requires_approval": (
                bool(s.overtime_requires_approval)
                if s.overtime_requires_approval is not None else None
            ),
        }
        for s in shifts
    ]

    settings = db.scalar(select(PayrollSettings).limit(1))
    settings_data = None
    if settings is not None:
        settings_data = {
            "sdl_applies": (
                bool(settings.sdl_applies) if settings.sdl_applies is not None else None
            ),
            "age_reference_date": settings.age_reference_date,
            "net_pay_floor": str(settings.net_pay_floor),
            "attendance_earning_map": dict(settings.attendance_earning_map or {}),
            "unpaid_day_behaviour": settings.unpaid_day_behaviour,
            "unpaid_day_formula_code": settings.unpaid_day_formula_code,
            "public_holiday_unworked_monthly": settings.public_holiday_unworked_monthly,
            "public_holiday_paid": (
                bool(settings.public_holiday_paid)
                if settings.public_holiday_paid is not None else None
            ),
            "leave_authoritative_source": settings.leave_authoritative_source,
            "monthly_hourly_derivation_formula_code":
                settings.monthly_hourly_derivation_formula_code,
            "leave_earning_for_monthly": (
                bool(settings.leave_earning_for_monthly)
                if settings.leave_earning_for_monthly is not None else None
            ),
        }

    return {
        "period": {
            "id": str(pay_period.id),
            "start_date": pay_period.start_date.isoformat(),
            "end_date": pay_period.end_date.isoformat(),
            "pay_date": pay_period.pay_date.isoformat(),
        },
        "employees": employee_data,
        "earnings": earnings_data,
        "earning_types": earning_types_data,
        "deductions": deductions_data,
        "deduction_types": deduction_types_data,
        "pay_history": history_data,
        "attendance_days": days_data,
        "attendance_segments": segments_data,
        "shifts": shifts_data,
        "settings": settings_data,
    }


def _compute_input_hash(db: Session, pay_period: PayPeriod) -> str:
    payload = _build_input_snapshot(db, pay_period)
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# M6 Part 2 Stage 3 — pending CR gate helpers (unchanged from Round 2)
# ---------------------------------------------------------------------------


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _parse_date_or_none(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _windows_overlap(
    a_from: date, a_to: date | None,
    b_from: date, b_to: date,
) -> bool:
    """Inclusive overlap test. a_to=None means ongoing."""
    if a_from > b_to:
        return False
    if a_to is not None and a_to < b_from:
        return False
    return True


def _load_target_row(db: Session, cr) -> EmployeeEarning | EmployeeDeduction | None:
    payload = cr.payload or {}
    target_id = payload.get("target_id")
    if not target_id:
        return None
    try:
        tid = uuid.UUID(str(target_id))
    except (ValueError, TypeError):
        return None
    if cr.kind.startswith("employee_earning_"):
        return db.scalar(
            select(EmployeeEarning).where(
                EmployeeEarning.id == tid,
                EmployeeEarning.employee_id == cr.employee_id,
            )
        )
    if cr.kind.startswith("employee_deduction_"):
        return db.scalar(
            select(EmployeeDeduction).where(
                EmployeeDeduction.id == tid,
                EmployeeDeduction.employee_id == cr.employee_id,
            )
        )
    return None


def _resolve_cr_windows(
    db: Session, cr,
) -> list[tuple[date | None, date | None]] | None:
    payload = cr.payload or {}
    kind = cr.kind
    try:
        if kind in ("employee_earning_create", "employee_deduction_create"):
            f = payload.get("effective_from")
            if not f:
                return None
            return [(
                _parse_date(f),
                _parse_date_or_none(payload.get("effective_to")),
            )]
        if kind in ("employee_earning_update", "employee_deduction_update"):
            existing = _load_target_row(db, cr)
            if existing is None:
                return None
            if "effective_from" in payload and payload["effective_from"] is not None:
                proposed_from = _parse_date(payload["effective_from"])
            else:
                proposed_from = existing.effective_from
            if "effective_to" in payload and payload["effective_to"] is not None:
                proposed_to = _parse_date(payload["effective_to"])
            else:
                proposed_to = existing.effective_to
            return [
                (existing.effective_from, existing.effective_to),
                (proposed_from, proposed_to),
            ]
        if kind in (
            "employee_earning_deactivate", "employee_deduction_deactivate",
        ):
            existing = _load_target_row(db, cr)
            if existing is None:
                return None
            return [(existing.effective_from, existing.effective_to)]
        return None
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def _cr_affects_target_period(
    db: Session, cr, period: PayPeriod,
) -> bool:
    if cr.kind == "employee_field_update":
        return True
    windows = _resolve_cr_windows(db, cr)
    if windows is None:
        return True
    if not windows:
        return True
    for wf, wt in windows:
        if wf is None:
            return True
        if _windows_overlap(wf, wt, period.start_date, period.end_date):
            return True
    return False


def _count_pending_change_requests_in_period(
    db: Session, pay_period: PayPeriod,
) -> tuple[int, list[dict]]:
    from app.db.tenant.models.change_request import PayrollChangeRequest

    rows = db.scalars(
        select(PayrollChangeRequest).where(
            PayrollChangeRequest.status == "pending",
        )
    ).all()
    blockers = [
        cr for cr in rows
        if _cr_affects_target_period(db, cr, pay_period)
    ]
    count = len(blockers)
    sample = [
        {
            "id": str(cr.id),
            "kind": cr.kind,
            "employee_id": str(cr.employee_id),
        }
        for cr in blockers[:5]
    ]
    return count, sample


def _cr_could_affect_locked_periods(
    db: Session, cr,
) -> tuple[PayPeriod | None, str | None]:
    if cr.kind == "employee_field_update":
        locked = db.scalar(
            select(PayPeriod)
            .join(Payslip, Payslip.pay_period_id == PayPeriod.id)
            .where(
                Payslip.employee_id == cr.employee_id,
                PayPeriod.status == "locked",
            )
            .limit(1)
        )
        if locked is not None:
            return locked, None
        return None, None

    windows = _resolve_cr_windows(db, cr)
    if windows is None:
        return None, "payload_unresolvable"
    if not windows:
        return None, "no_effective_windows"
    for wf, wt in windows:
        if wf is None:
            return None, "effective_from_missing"
        stmt = (
            select(PayPeriod)
            .where(PayPeriod.status == "locked")
            .where(PayPeriod.end_date >= wf)
        )
        if wt is not None:
            stmt = stmt.where(PayPeriod.start_date <= wt)
        locked = db.scalar(stmt.limit(1))
        if locked is not None:
            return locked, None
    return None, None


def _lock_period(db: Session, pay_period_id: uuid.UUID) -> PayPeriod:
    return db.execute(
        select(PayPeriod)
        .where(PayPeriod.id == pay_period_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def run_preview(db: Session, user, pay_period: PayPeriod) -> PayrollRun:
    pay_period = _lock_period(db, pay_period.id)

    if pay_period.status == "locked":
        raise AppError("period_locked", "Cannot preview a finalised period; reopen it first", 409)

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
        kind="preview",
        revision=rev,
        status="running",
        rules_snapshot={},
        started_by_user_id=getattr(user, "id", None),
    )
    db.add(run)
    db.flush()

    warnings = _formula_warnings(db)
    # Stage 4: hash the input state BEFORE the pipeline writes anything
    # calc-affecting. The hash captures the reviewed inputs; finalise
    # compares against a fresh hash of current inputs.
    run.rules_snapshot = {
        "preview": True,
        "unacknowledged_formulas": warnings,
        "employee_count": 0,
        "input_hash": _compute_input_hash(db, pay_period),
    }

    employees = _in_scope_employees(db)
    for emp in employees:
        config = build_pipeline_config(db, emp, pay_period.pay_date)
        earnings, attn_warnings, attn_snapshot = _build_all_earnings(db, emp, pay_period)
        deductions = _build_deductions(db, emp, pay_period.pay_date)
        draft = P.run_pipeline(config, earnings, deductions, [])
        if draft.refused:
            run.status = "failed"
            run.error_code = draft.refusal_code
            run.error_detail = f"employee {emp.employee_code}: {draft.refusal_message}"
            run.completed_at = datetime.now(timezone.utc)
            db.flush()
            raise AppError(draft.refusal_code or "compute_refused", draft.refusal_message or "", 409)
        draft.calculation_context["attendance_warnings"] = attn_warnings
        draft.calculation_context["attendance_inputs"] = attn_snapshot
        _write_payslip(
            db, run, pay_period, emp, draft,
            earnings=earnings, deductions=deductions,
            status="preview", prior=None,
        )
        run.rules_snapshot["employee_count"] = run.rules_snapshot["employee_count"] + 1

    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    db.flush()
    write_audit(
        db, user,
        entity_type="payroll_run", entity_id=run.id, action="preview",
        new_value={
            "pay_period_id": str(pay_period.id),
            "employee_count": run.rules_snapshot["employee_count"],
            "input_hash": run.rules_snapshot.get("input_hash"),
        },
    )
    return run


def finalise(
    db: Session, user, pay_period: PayPeriod,
    *, ack_open_exceptions_reason: str | None = None,
    ack_stale_preview_reason: str | None = None,
) -> PayrollRun:
    pay_period = _lock_period(db, pay_period.id)

    if pay_period.status == "locked":
        raise AppError("period_locked", "Period is already finalised", 409)

    warnings = _formula_warnings(db)
    if warnings:
        raise AppError(
            "formula_unacknowledged",
            f"cannot finalise until all formulas are acknowledged; missing: {warnings}",
            409,
        )

    open_count, open_sample = _count_open_exceptions_in_period(db, pay_period)
    ack_used = False
    if open_count > 0:
        if not ack_open_exceptions_reason or not ack_open_exceptions_reason.strip():
            raise AppError(
                "open_exceptions_in_period",
                f"{open_count} open exception(s) exist in this period; pass "
                f"ack_open_exceptions_reason to acknowledge and proceed",
                409,
                {"count": open_count, "sample": open_sample},
            )
        ack_used = True

    # Stage 3: pending CRs.
    pending_cr_count, pending_cr_sample = _count_pending_change_requests_in_period(
        db, pay_period,
    )
    if pending_cr_count > 0:
        raise AppError(
            "pending_change_requests_in_period",
            f"{pending_cr_count} pending change request(s) could affect this "
            f"period; approve, reject, or cancel them before finalising",
            409,
            {"count": pending_cr_count, "sample": pending_cr_sample},
        )

    # Stage 4: stale-preview gate.
    #
    # Compute the current input hash. If a preview run exists and its stored
    # hash differs, the admin reviewed a different set of inputs. Block
    # unless acknowledged.
    #
    # No preview run at all → skip. This preserves the pre-Stage-4 contract
    # where finalise without a prior preview was allowed.
    #
    # Residual race (documented, not fully closed): a CR approved between
    # the pending-CR gate above and the hash snapshot below lands inside
    # the current transaction's window; the hash will not see it, and the
    # resulting payslips will reflect it. Fully closing that requires CR
    # approval to take the pay_period row lock — Stage 2b territory.
    current_hash = _compute_input_hash(db, pay_period)
    stale_used = False
    preview_run = db.scalar(
        select(PayrollRun)
        .where(
            PayrollRun.pay_period_id == pay_period.id,
            PayrollRun.kind == "preview",
        )
        .order_by(PayrollRun.started_at.desc())
        .limit(1)
    )
    if preview_run is not None:
        stored_hash = (preview_run.rules_snapshot or {}).get("input_hash")
        if stored_hash != current_hash:
            if not ack_stale_preview_reason or not ack_stale_preview_reason.strip():
                raise AppError(
                    "preview_stale",
                    "inputs changed since last preview; re-run preview or pass "
                    "ack_stale_preview_reason to override",
                    409,
                    {
                        "preview_hash": stored_hash,
                        "current_hash": current_hash,
                    },
                )
            stale_used = True

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
    run.rules_snapshot = {
        "final": True,
        "employee_count": 0,
        "revision": rev,
        "input_hash": current_hash,
    }

    for emp in employees:
        prior = db.scalar(
            select(Payslip).where(
                Payslip.pay_period_id == pay_period.id,
                Payslip.employee_id == emp.id,
                Payslip.status == "current",
            )
        )
        config = build_pipeline_config(db, emp, pay_period.pay_date)
        earnings, attn_warnings, attn_snapshot = _build_all_earnings(db, emp, pay_period)
        deductions = _build_deductions(db, emp, pay_period.pay_date)
        draft = P.run_pipeline(config, earnings, deductions, [])
        if draft.refused:
            run.status = "failed"
            run.error_code = draft.refusal_code
            run.error_detail = f"employee {emp.employee_code}: {draft.refusal_message}"
            run.completed_at = datetime.now(timezone.utc)
            db.flush()
            raise AppError(draft.refusal_code or "compute_refused", draft.refusal_message or "", 409)
        draft.calculation_context["attendance_warnings"] = attn_warnings
        draft.calculation_context["attendance_inputs"] = attn_snapshot
        _write_payslip(
            db, run, pay_period, emp, draft,
            earnings=earnings, deductions=deductions,
            status="current", prior=prior,
        )
        run.rules_snapshot["employee_count"] = run.rules_snapshot["employee_count"] + 1

    pay_period.status = "locked"
    pay_period.row_version += 1
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    db.flush()
    write_audit(
        db, user,
        entity_type="payroll_run", entity_id=run.id, action="finalise",
        new_value={
            "pay_period_id": str(pay_period.id),
            "revision": rev,
            "employee_count": run.rules_snapshot["employee_count"],
            "open_exception_count_at_finalise": open_count,
            "ack_open_exceptions_reason": ack_open_exceptions_reason if ack_used else None,
            "pending_cr_count_at_finalise": pending_cr_count,
            "stale_preview_acked": bool(stale_used),
            "ack_stale_preview_reason": ack_stale_preview_reason if stale_used else None,
            "input_hash": current_hash,
        },
    )
    return run


def reopen(db: Session, user, pay_period: PayPeriod, reason: str) -> PeriodReopenLog:
    pay_period = _lock_period(db, pay_period.id)

    if pay_period.status != "locked":
        raise AppError("period_not_locked", "Only a locked period can be reopened", 409)

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


def run_preview_for_employee_as_of(
    db: Session,
    user,
    pay_period: PayPeriod,
    employee: Employee,
    as_of: date,
) -> dict:
    if pay_period.status == "locked":
        raise AppError(
            "period_locked",
            "Cannot preview a finalised period; reopen it first",
            409,
        )
    if as_of < pay_period.start_date:
        raise AppError(
            "as_of_before_period_start",
            f"as_of ({as_of.isoformat()}) is before period start "
            f"({pay_period.start_date.isoformat()})",
            422,
        )
    if as_of > pay_period.end_date:
        as_of = pay_period.end_date

    base = {
        "employee_id": employee.id,
        "employee_code": employee.employee_code,
        "employee_name": f"{employee.first_name} {employee.last_name}".strip(),
        "pay_period_id": pay_period.id,
        "revision": None,
        "status": "as_of",
        "as_of": as_of,
        "gross": None,
        "paye": None,
        "net": None,
        "warnings": [],
        "lines": [],
        "deductions": [],
        "available": False,
        "reason_unavailable": None,
    }

    if employee.pay_basis not in ("hourly", "daily"):
        base["reason_unavailable"] = "monthly_proration_pending"
        return base

    config = build_pipeline_config(db, employee, pay_period.pay_date)
    earnings, attn_warnings, attn_snapshot = _build_all_earnings(
        db, employee, pay_period, through_date=as_of,
    )
    deductions = _build_deductions(db, employee, as_of)
    draft = P.run_pipeline(config, earnings, deductions, [])
    if draft.refused:
        base["reason_unavailable"] = draft.refusal_code or "compute_refused"
        base["warnings"] = list(attn_warnings) + [
            draft.refusal_message or "",
        ]
        return base

    base["available"] = True
    base["gross"] = draft.gross
    base["paye"] = draft.paye
    base["net"] = draft.net
    base["warnings"] = list(attn_warnings)
    base["lines"] = [
        {
            "earning_type_code": (
                ln.source_ref.get("earning_type_code", "")
                if ln.source_ref else ""
            ),
            "earning_type_name": ln.label,
            "rate_source": (
                "attendance"
                if ln.source_ref and ln.source_ref.get("attendance_derived")
                else "fixed"
            ),
            "amount": ln.amount,
            "minutes": (
                ln.source_ref.get("minutes")
                if ln.source_ref else None
            ),
        }
        for ln in earnings
    ]
    base["deductions"] = [
        {
            "deduction_type_code": (d.source_ref or {}).get("deduction_type_code", ""),
            "deduction_type_name": getattr(d, "label", "") or "",
            "amount": d.amount,
        }
        for d in deductions
    ]
    return base