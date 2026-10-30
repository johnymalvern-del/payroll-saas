"""UIF, SDL, and retirement-limit calculators (Chapter 4, Bundle 004a-iii part 1).

Pure functions. No DB, no clock, no side effects. Callers supply the
effective-dated statutory tables (from payroll_tax.load_tax_tables or the
equivalent row-dict loaders) as plain dicts. Values are NOT baked in — no
statutory number appears anywhere in this file.

Rules encoded (E4, E7, D10):
  UIF: ceiling applies to the base BEFORE the rate (per SARS practice); rate
       then applied; result rounded 2dp half-up.
  UIF employer: identical mechanics with employer_rate.
  SDL: employer cost only, not an employee deduction. Refuses when the tenant
       setting `sdl_applies` is None (deliberately unset).
  Retirement 11F cap: min(percentage_of_taxable_income * period_gross,
       annual_cap / periods_per_year). The employee's intended contribution is
       then capped at this value (excess carried forward is deferred — see
       004a-iii part 2).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.services import payroll_refusals as R


def _q(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _dec(v: Any) -> Decimal:
    return Decimal(str(v))


def _value_of(row: dict) -> Decimal:
    if "amount" in row:
        return _dec(row["amount"])
    if "value" in row:
        return _dec(row["value"])
    raise R.PayrollRefusal(
        R.STATUTORY_TABLE_INVALID,
        f"statutory row {row.get('row_key')!r} has neither 'amount' nor 'value'",
        500,
    )


def _as_dict(rows: list[dict]) -> dict[str, Decimal]:
    """Turn statutory_table rows into {row_key: decimal}."""
    return {row["row_key"]: _value_of(row) for row in rows}


# ---------------------------------------------------------------------------
# UIF
# ---------------------------------------------------------------------------

def compute_uif_employee(
    period_gross_for_uif: Decimal,
    uif_rows: list[dict],
    uif_exempt: bool = False,
) -> Decimal:
    if uif_exempt:
        return Decimal("0.00")
    t = _as_dict(uif_rows)
    rate = t.get("employee_rate")
    ceiling = t.get("monthly_ceiling")
    if rate is None or ceiling is None:
        raise R.PayrollRefusal(
            R.UIF_CEILING_MISSING,
            "uif table is missing employee_rate and/or monthly_ceiling",
            409,
        )
    base = min(period_gross_for_uif, ceiling)
    return _q(base * rate)


def compute_uif_employer(
    period_gross_for_uif: Decimal,
    uif_rows: list[dict],
    uif_exempt: bool = False,
) -> Decimal:
    if uif_exempt:
        return Decimal("0.00")
    t = _as_dict(uif_rows)
    rate = t.get("employer_rate")
    ceiling = t.get("monthly_ceiling")
    if rate is None or ceiling is None:
        raise R.PayrollRefusal(
            R.UIF_CEILING_MISSING,
            "uif table is missing employer_rate and/or monthly_ceiling",
            409,
        )
    base = min(period_gross_for_uif, ceiling)
    return _q(base * rate)


# ---------------------------------------------------------------------------
# SDL (employer cost only)
# ---------------------------------------------------------------------------

def compute_sdl(
    period_gross_for_sdl: Decimal,
    sdl_rows: list[dict],
    sdl_applies: bool | None,
) -> Decimal:
    if sdl_applies is None:
        raise R.PayrollRefusal(
            R.SDL_APPLIES_UNSET,
            "tenant setting payroll.sdl_applies is unset; set it before first finalise",
            409,
        )
    if not sdl_applies:
        return Decimal("0.00")
    t = _as_dict(sdl_rows)
    rate = t.get("rate")
    if rate is None:
        raise R.PayrollRefusal(
            R.STATUTORY_TABLE_MISSING,
            "sdl table is missing rate",
            409,
        )
    return _q(period_gross_for_sdl * rate)


# ---------------------------------------------------------------------------
# Retirement 11F cap
# ---------------------------------------------------------------------------

def compute_retirement_limit(
    period_gross: Decimal,
    retirement_rows: list[dict],
    periods_per_year: int,
) -> Decimal:
    """Maximum retirement-fund deduction for one pay period.

    Returns min(percentage_of_taxable_income * period_gross,
               annual_cap / periods_per_year), rounded 2dp.
    The caller then takes min(intended_deduction, limit) to determine how much
    actually reduces taxable income this period.
    """
    if periods_per_year <= 0:
        raise R.PayrollRefusal(
            R.STATUTORY_TABLE_INVALID,
            "periods_per_year must be positive",
            500,
        )
    t = _as_dict(retirement_rows)
    pct = t.get("percentage_of_taxable_income")
    cap = t.get("annual_cap")
    if pct is None or cap is None:
        raise R.PayrollRefusal(
            R.RETIREMENT_LIMIT_MISSING,
            "retirement_limit table is missing percentage_of_taxable_income and/or annual_cap",
            409,
        )
    per_period_cap = cap / Decimal(periods_per_year)
    by_pct = period_gross * pct
    return _q(min(by_pct, per_period_cap))


def apply_retirement_limit(
    intended_contribution: Decimal,
    period_gross: Decimal,
    retirement_rows: list[dict],
    periods_per_year: int,
) -> tuple[Decimal, Decimal]:
    """Return (allowed_deduction, excess_carried_forward)."""
    if intended_contribution < 0:
        raise R.PayrollRefusal(
            R.STATUTORY_TABLE_INVALID,
            "intended_contribution must be non-negative",
            500,
        )
    limit = compute_retirement_limit(period_gross, retirement_rows, periods_per_year)
    allowed = min(intended_contribution, limit)
    excess = max(Decimal("0.00"), intended_contribution - allowed)
    return allowed, excess

# END OF FILE
