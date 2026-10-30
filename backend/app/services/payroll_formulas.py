"""Payroll earnings-generation formulas (Chapter 4, Bundle 004a-i).

Each gen_* function is pure: no DB, no clock, no side effects. Inputs are
explicit and, where a statutory multiplier is needed, the parameter has NO
default — the pipeline must supply it from an acknowledged source. This
respects the "no invented statutory values" rule while letting the functions
be tested today with clearly-fake fixture values.

FORMULA_REGISTRY lists every formula. Each must be acknowledged by the
payroll admin (F8) before first finalise; readiness endpoint surfaces which
are outstanding.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP


VALID_PREMIUM_MODES = ("full", "none", "hourly_equivalent")


FORMULA_REGISTRY: dict[str, str] = {
    "gen_base_salary":
        "Full-period base monthly salary",
    "gen_part_period_joiner_leaver":
        "Prorated base salary for mid-period hire or termination (calendar-day fraction)",
    "gen_unpaid_absence":
        "Daily rate x unpaid absence days",
    "gen_salaried_premiums":
        "Salaried premium pay per shift premium mode (full/none/hourly_equivalent)",
    "gen_paid_leave":
        "Daily rate x paid leave days",
    "gen_public_holiday_unworked":
        "Unworked public holiday pay per country policy (requires explicit multiplier)",
}


def _q(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def gen_base_salary(*, monthly_amount: Decimal) -> Decimal:
    """Full-period base salary. Monthly amount quantised to 2 dp half-up."""
    return _q(monthly_amount)


def gen_part_period_joiner_leaver(
    *,
    monthly_amount: Decimal,
    hired_on: date | None,
    terminated_on: date | None,
    period_start: date,
    period_end: date,
) -> Decimal:
    """Calendar-day proration for joiner/leaver within [period_start, period_end]."""
    full_start = max(period_start, hired_on) if hired_on else period_start
    full_end = min(period_end, terminated_on) if terminated_on else period_end
    if full_end < full_start:
        return Decimal("0.00")
    days_present = (full_end - full_start).days + 1
    days_in_period = (period_end - period_start).days + 1
    return _q(monthly_amount * Decimal(days_present) / Decimal(days_in_period))


def gen_unpaid_absence(
    *,
    daily_rate: Decimal,
    unpaid_days: Decimal,
) -> Decimal:
    """Daily rate x unpaid absence days."""
    return _q(daily_rate * unpaid_days)


def gen_salaried_premiums(
    *,
    salaried_premium_mode: str,
    hourly_rate: Decimal,
    premium_hours: Decimal,
    premium_multiplier: Decimal | None = None,
) -> Decimal:
    """Salaried premium pay.

    - 'full': salary already covers it -> 0
    - 'none': never any premium -> 0
    - 'hourly_equivalent': hourly_rate * premium_hours * premium_multiplier
      premium_multiplier has no default; the pipeline must supply it.
    """
    if salaried_premium_mode in ("full", "none"):
        return Decimal("0.00")
    if salaried_premium_mode == "hourly_equivalent":
        if premium_multiplier is None:
            raise ValueError(
                "salaried_premium_mode='hourly_equivalent' requires "
                "premium_multiplier (no default by design)"
            )
        return _q(hourly_rate * premium_hours * premium_multiplier)
    raise ValueError(f"unknown salaried_premium_mode: {salaried_premium_mode!r}")


def gen_paid_leave(
    *,
    daily_rate: Decimal,
    paid_leave_days: Decimal,
) -> Decimal:
    """Daily rate x paid leave days."""
    return _q(daily_rate * paid_leave_days)


def gen_public_holiday_unworked(
    *,
    daily_rate: Decimal,
    holiday_days: Decimal,
    public_holiday_pay_multiplier: Decimal | None = None,
) -> Decimal:
    """Unworked public holiday pay.

    The statutory multiplier varies by jurisdiction and cannot be baked in.
    Caller must supply public_holiday_pay_multiplier; None raises.
    """
    if public_holiday_pay_multiplier is None:
        raise ValueError(
            "gen_public_holiday_unworked requires public_holiday_pay_multiplier "
            "(no default by design)"
        )
    return _q(daily_rate * holiday_days * public_holiday_pay_multiplier)


def hourly_rate_from_monthly(
    *,
    monthly_salary: Decimal,
    contracted_weekly_hours: Decimal,
) -> Decimal:
    """D4 formula (subject to accountant confirmation).

    monthly_hours = contracted_weekly_hours * 52 / 12
    hourly_rate   = monthly_salary / monthly_hours
    Returned to 4 dp half-up.
    """
    if contracted_weekly_hours <= 0:
        raise ValueError("contracted_weekly_hours must be positive")
    monthly_hours = contracted_weekly_hours * Decimal(52) / Decimal(12)
    return (monthly_salary / monthly_hours).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )

# END OF FILE
