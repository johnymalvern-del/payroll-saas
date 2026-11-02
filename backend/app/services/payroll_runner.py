"""Payroll runner (Chapter 4 Bundle 004b-a + Chapter 4H B-4c).

Orchestration layer between HTTP endpoints and the pure pipeline.

Chapter 4H B-4c adds attendance-to-earnings integration:
  - `_build_attendance_earnings` reads attendance_day + attendance_segment
    rows for the period and produces EarningLines per attendance_earning_map.
  - Locked days are INCLUDED (round-2 §1) — a closed period must not lose
    its own data on re-preview.
  - Unapproved overtime segments produce a warning and no earning (round-2 §6).
  - Unpaid days and unpaid public holidays produce NEGATIVE earning lines so
    they reduce gross BEFORE PAYE/UIF/SDL (round-2 §3). The amount is
    computed by the accountant-acknowledged `unpaid_day_formula_code`, never
    an invented divisor.
  - Monthly staff hourly rates are derived via
    `monthly_hourly_derivation_formula_code` when they have overtime or
    allowance segments (round-2 §4).
  - Rate in force uses `EmployeePayHistory` (effective-dated) for the
    segment's `local_date`, not the current `employee.base_rate`
    (round-2 §5). A missing history row falls back to `employee.base_rate`
    with a warning, never silently.
  - Leave source restricted to 'adjustment' (round-2 §9): any other value
    raises 422 `leave_source_not_available`.
  - The attendance inputs (grouped minutes, mapping used, settings read,
    rate sources) are stored on `draft.calculation_context["attendance_inputs"]`
    so explain/PDF can reproduce what the run used (round-2 §10).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tenant.models.attendance import (
    AttendanceDay,
    AttendanceSegment,
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

# Formulas the runner can actually invoke for unpaid_day_formula_code.
# The PATCH validator accepts any FORMULA_REGISTRY code, but only these three
# have the (daily_rate, unpaid_days) signature the runner expects.
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
    """Pay rate in force on `on_date`.

    - hourly: newest approved pay history row with effective_from <= on_date,
      else employee.base_rate with a warning.
    - monthly: hourly equivalent derived via
      settings.monthly_hourly_derivation_formula_code. Unset -> 409.
    """
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

    # monthly
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
    """Daily rate for unpaid-day / leave-pay / public-holiday computations.

    rate = hourly_rate_in_force * (hours_in_standard_day)
    hours_in_standard_day = default_shift.length_minutes / 60
                             OR contracted_weekly_hours / 5
    Never invents an 8-hour divisor — the shift or the contracted hours are
    real employee data.
    """
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


def _segment_amount(
    seg: AttendanceSegment,
    rate: Decimal,
) -> Decimal:
    """Amount for a single multiplier segment.

    round-2 §7: Decimal throughout; per-segment quantisation to 4 dp, then
    the final aggregated line is quantised to 2 dp by the pipeline.
    """
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
) -> tuple[list[P.EarningLine], list[str], dict]:
    """Attendance-derived EarningLines for the period.

    Returns (lines, warnings, snapshot). Lines may include NEGATIVE entries
    (unpaid days / unpaid public holidays) which reduce gross before tax.
    """
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
        },
    }
    lines: list[P.EarningLine] = []

    # Leave source gate (round-2 §9): only 'adjustment' supported.
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
    if not days:
        return [], warnings, snapshot

    day_by_id = {d.id: d for d in days}
    segments = list(db.scalars(
        select(AttendanceSegment).where(
            AttendanceSegment.attendance_day_id.in_(list(day_by_id.keys()))
        )
    ).all())

    # 1. Group minutes by (kind, day_type, tier).
    grouped: dict[str, int] = {}
    for seg in segments:
        if seg.minutes <= 0:
            continue
        key = _group_key_for_segment(seg)
        grouped[key] = grouped.get(key, 0) + int(seg.minutes)
    snapshot["grouped_minutes"] = dict(grouped)

    # 2. Resolve mapping.
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

    # 3. Load earning types referenced.
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

    # 4. Per-segment rate & amount -> aggregate by earning_type code.
    agg: dict[str, dict] = {}
    for seg in segments:
        if seg.minutes <= 0:
            continue
        day = day_by_id.get(seg.attendance_day_id)
        if day is None:
            continue
        # Normal segments for monthly staff are already covered by
        # BASE_MONTHLY — do not double-pay them.
        if employee.pay_basis == "monthly" and seg.kind == "normal":
            continue

        key = _group_key_for_segment(seg)
        code = mapping[key]
        et = types_by_code[code]

        # Overtime approval gate (round-2 §6).
        if seg.kind == "overtime":
            shift = db.get(Shift, day.shift_id) if day.shift_id else None
            requires_approval = bool(shift and shift.overtime_requires_approval)
            if requires_approval and seg.overtime_status != "approved":
                warnings.append(
                    f"overtime_unapproved:{employee.employee_code}:"
                    f"{day.work_date.isoformat()}:{seg.minutes}min"
                )
                continue

        # Rate in force on segment local_date (round-2 §5).
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

    # 5. Unpaid days (round-2 §3): monthly staff only, negative earning.
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
                # Hourly staff lose pay by not working; no negative needed.
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
                    amount=-positive,  # NEGATIVE reduces gross
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

    # 6. Unworked public holidays (round-2 §3).
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
            # Monthly salary covers it; hourly staff get nothing extra (no
            # hours worked). Both are consistent with "paid holiday" for
            # salaried and "no hours" for hourly.
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

    # 7. Leave (adjustment source only).
    leave_days = [d for d in days if d.status == "leave"]
    if leave_days:
        if settings.leave_authoritative_source is None:
            raise AppError(
                "leave_source_not_configured",
                "payroll.leave_authoritative_source is unset but "
                f"{len(leave_days)} leave day(s) exist in the period",
                409,
            )
        # Already asserted only 'adjustment' accepted above.
        if employee.pay_basis == "monthly" and not bool(settings.leave_earning_for_monthly):
            pass  # salary covers it
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
) -> tuple[list[P.EarningLine], list[str], dict]:
    fixed = _build_fixed_earnings(db, employee, pay_period.pay_date)
    attn, warnings, snapshot = _build_attendance_earnings(db, employee, pay_period)
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


def run_preview(db: Session, user, pay_period: PayPeriod) -> PayrollRun:
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
    run.rules_snapshot = {
        "preview": True,
        "unacknowledged_formulas": warnings,
        "employee_count": 0,
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


def reopen(db: Session, user, pay_period: PayPeriod, reason: str) -> PeriodReopenLog:
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
