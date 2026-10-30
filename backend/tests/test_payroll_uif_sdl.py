"""UIF / SDL / retirement-limit calculators (Chapter 4, Bundle 004a-iii part 1).

Every expected figure is hand-worked in the comment. Fixtures are synthetic —
no real statutory number appears anywhere.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services import payroll_refusals as R
from app.services import payroll_uif_sdl as U


# ---------------------------------------------------------------------------
# Synthetic fixtures (obviously fake)
# ---------------------------------------------------------------------------

UIF_ROWS = [
    {"row_key": "employee_rate", "value": "0.01"},
    {"row_key": "employer_rate", "value": "0.01"},
    {"row_key": "monthly_ceiling", "value": "500"},
]

SDL_ROWS = [
    {"row_key": "rate", "value": "0.01"},
    {"row_key": "exemption_threshold_annual", "value": "50000"},
]

RETIREMENT_ROWS = [
    {"row_key": "percentage_of_taxable_income", "value": "0.10"},
    {"row_key": "annual_cap", "value": "1000"},
]


# ---------------------------------------------------------------------------
# UIF employee
# ---------------------------------------------------------------------------

def test_uif_employee_under_ceiling():
    # base 300, 1% = 3.00
    assert U.compute_uif_employee(Decimal(300), UIF_ROWS) == Decimal("3.00")


def test_uif_employee_at_ceiling():
    # base 500, 1% = 5.00
    assert U.compute_uif_employee(Decimal(500), UIF_ROWS) == Decimal("5.00")


def test_uif_employee_above_ceiling_capped():
    # base 1000 but ceiling 500, so 500*1% = 5.00
    assert U.compute_uif_employee(Decimal(1000), UIF_ROWS) == Decimal("5.00")


def test_uif_employee_rounds_half_up():
    # base 333, 1% = 3.33 (exactly)
    # base 355, 1% = 3.55
    # base 355.5 would need half-up; use 355.5 * 0.01 = 3.555 -> 3.56
    rows = [
        {"row_key": "employee_rate", "value": "0.01"},
        {"row_key": "employer_rate", "value": "0.01"},
        {"row_key": "monthly_ceiling", "value": "10000"},
    ]
    assert U.compute_uif_employee(Decimal("355.50"), rows) == Decimal("3.56")


def test_uif_employee_exempt_returns_zero():
    assert U.compute_uif_employee(Decimal(1000), UIF_ROWS, uif_exempt=True) == Decimal("0.00")


def test_uif_employee_missing_rate_raises():
    rows = [{"row_key": "monthly_ceiling", "value": "500"}]
    with pytest.raises(R.PayrollRefusal) as exc_info:
        U.compute_uif_employee(Decimal(100), rows)
    assert exc_info.value.code == R.UIF_CEILING_MISSING


# ---------------------------------------------------------------------------
# UIF employer
# ---------------------------------------------------------------------------

def test_uif_employer_under_ceiling():
    # base 300, 1% = 3.00
    assert U.compute_uif_employer(Decimal(300), UIF_ROWS) == Decimal("3.00")


def test_uif_employer_above_ceiling_capped():
    assert U.compute_uif_employer(Decimal(5000), UIF_ROWS) == Decimal("5.00")


def test_uif_employer_exempt_returns_zero():
    assert U.compute_uif_employer(Decimal(1000), UIF_ROWS, uif_exempt=True) == Decimal("0.00")


# ---------------------------------------------------------------------------
# SDL
# ---------------------------------------------------------------------------

def test_sdl_applies_true():
    # base 1000, 1% = 10.00
    assert U.compute_sdl(Decimal(1000), SDL_ROWS, sdl_applies=True) == Decimal("10.00")


def test_sdl_applies_false_returns_zero():
    assert U.compute_sdl(Decimal(1000), SDL_ROWS, sdl_applies=False) == Decimal("0.00")


def test_sdl_unset_raises():
    with pytest.raises(R.PayrollRefusal) as exc_info:
        U.compute_sdl(Decimal(1000), SDL_ROWS, sdl_applies=None)
    assert exc_info.value.code == R.SDL_APPLIES_UNSET


def test_sdl_missing_rate_raises():
    rows = [{"row_key": "exemption_threshold_annual", "value": "50000"}]
    with pytest.raises(R.PayrollRefusal) as exc_info:
        U.compute_sdl(Decimal(1000), rows, sdl_applies=True)
    assert exc_info.value.code == R.STATUTORY_TABLE_MISSING


# ---------------------------------------------------------------------------
# Retirement 11F cap
# ---------------------------------------------------------------------------

def test_retirement_limit_pct_binds():
    # 1000 * 10% = 100; cap/12 = 1000/12 = 83.33
    # min(100, 83.33) = 83.33
    assert U.compute_retirement_limit(
        Decimal(1000), RETIREMENT_ROWS, periods_per_year=12,
    ) == Decimal("83.33")


def test_retirement_limit_cap_binds():
    # 10000 * 10% = 1000; cap/12 = 83.33
    # min(1000, 83.33) = 83.33
    assert U.compute_retirement_limit(
        Decimal(10000), RETIREMENT_ROWS, periods_per_year=12,
    ) == Decimal("83.33")


def test_retirement_limit_pct_binds_low_income():
    # 100 * 10% = 10; cap/12 = 83.33
    # min(10, 83.33) = 10.00
    assert U.compute_retirement_limit(
        Decimal(100), RETIREMENT_ROWS, periods_per_year=12,
    ) == Decimal("10.00")


def test_retirement_limit_zero_periods_raises():
    with pytest.raises(R.PayrollRefusal):
        U.compute_retirement_limit(Decimal(100), RETIREMENT_ROWS, periods_per_year=0)


def test_retirement_limit_missing_pct_raises():
    rows = [{"row_key": "annual_cap", "value": "1000"}]
    with pytest.raises(R.PayrollRefusal) as exc_info:
        U.compute_retirement_limit(Decimal(100), rows, periods_per_year=12)
    assert exc_info.value.code == R.RETIREMENT_LIMIT_MISSING


def test_apply_retirement_limit_under():
    # intended 50, limit 83.33 -> allowed 50, excess 0
    allowed, excess = U.apply_retirement_limit(
        Decimal(50), Decimal(1000), RETIREMENT_ROWS, periods_per_year=12,
    )
    assert allowed == Decimal(50)
    assert excess == Decimal("0.00")


def test_apply_retirement_limit_over():
    # intended 200, limit 83.33 -> allowed 83.33, excess 116.67
    allowed, excess = U.apply_retirement_limit(
        Decimal(200), Decimal(1000), RETIREMENT_ROWS, periods_per_year=12,
    )
    assert allowed == Decimal("83.33")
    assert excess == Decimal("116.67")


def test_apply_retirement_limit_negative_raises():
    with pytest.raises(R.PayrollRefusal):
        U.apply_retirement_limit(
            Decimal(-1), Decimal(1000), RETIREMENT_ROWS, periods_per_year=12,
        )

# END OF FILE
