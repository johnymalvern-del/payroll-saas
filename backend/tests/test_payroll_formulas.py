"""Payroll formula pure-function tests (Chapter 4, Bundle 004a-i).

No DB. Every expected value is hand-worked below the assertion so a reader
can verify the arithmetic without running Python.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services import payroll_formulas as pf


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_formula_registry_has_six_entries():
    assert len(pf.FORMULA_REGISTRY) == 6
    expected = {
        "gen_base_salary", "gen_part_period_joiner_leaver",
        "gen_unpaid_absence", "gen_salaried_premiums",
        "gen_paid_leave", "gen_public_holiday_unworked",
    }
    assert set(pf.FORMULA_REGISTRY.keys()) == expected


def test_every_registered_formula_is_callable():
    for code in pf.FORMULA_REGISTRY:
        fn = getattr(pf, code, None)
        assert callable(fn), f"{code} is in registry but not a callable in module"


# ---------------------------------------------------------------------------
# gen_base_salary
# ---------------------------------------------------------------------------

def test_gen_base_salary_full_period():
    # 25_000.00 in, 25_000.00 out
    assert pf.gen_base_salary(monthly_amount=Decimal("25000.00")) == Decimal("25000.00")


def test_gen_base_salary_quantizes_half_up():
    # 25_000.005 rounds to 25_000.01 (half-up)
    assert pf.gen_base_salary(monthly_amount=Decimal("25000.005")) == Decimal("25000.01")


# ---------------------------------------------------------------------------
# gen_part_period_joiner_leaver
# ---------------------------------------------------------------------------

def test_gen_part_period_joiner_leaver_full_period():
    # Hired 2024-01-01, no termination, period 2025-05-01..2025-05-31 -> full month
    result = pf.gen_part_period_joiner_leaver(
        monthly_amount=Decimal("25000.00"),
        hired_on=date(2024, 1, 1),
        terminated_on=None,
        period_start=date(2025, 5, 1),
        period_end=date(2025, 5, 31),
    )
    assert result == Decimal("25000.00")


def test_gen_part_period_joiner_leaver_mid_month():
    # 31000 * 16 / 31 = 16000.00 exactly (16 days present: 2025-05-16..2025-05-31)
    result = pf.gen_part_period_joiner_leaver(
        monthly_amount=Decimal("31000.00"),
        hired_on=date(2025, 5, 16),
        terminated_on=None,
        period_start=date(2025, 5, 1),
        period_end=date(2025, 5, 31),
    )
    assert result == Decimal("16000.00")


def test_gen_part_period_joiner_leaver_terminated_mid_month():
    # 31000 * 15 / 31 = 15000.00 exactly (15 days: 2025-05-01..2025-05-15)
    result = pf.gen_part_period_joiner_leaver(
        monthly_amount=Decimal("31000.00"),
        hired_on=None,
        terminated_on=date(2025, 5, 15),
        period_start=date(2025, 5, 1),
        period_end=date(2025, 5, 31),
    )
    assert result == Decimal("15000.00")


def test_gen_part_period_joiner_leaver_empty_window():
    # Terminated before period starts -> 0
    result = pf.gen_part_period_joiner_leaver(
        monthly_amount=Decimal("25000.00"),
        hired_on=None,
        terminated_on=date(2025, 4, 30),
        period_start=date(2025, 5, 1),
        period_end=date(2025, 5, 31),
    )
    assert result == Decimal("0.00")


# ---------------------------------------------------------------------------
# gen_unpaid_absence
# ---------------------------------------------------------------------------

def test_gen_unpaid_absence_basic():
    # daily_rate 800.00 * 3 unpaid days = 2400.00
    assert pf.gen_unpaid_absence(
        daily_rate=Decimal("800.00"), unpaid_days=Decimal("3"),
    ) == Decimal("2400.00")


def test_gen_unpaid_absence_zero_days():
    assert pf.gen_unpaid_absence(
        daily_rate=Decimal("800.00"), unpaid_days=Decimal("0"),
    ) == Decimal("0.00")


# ---------------------------------------------------------------------------
# gen_salaried_premiums
# ---------------------------------------------------------------------------

def test_gen_salaried_premiums_full_mode_returns_zero():
    # 'full' means salary already covers premiums -> 0 regardless of inputs
    assert pf.gen_salaried_premiums(
        salaried_premium_mode="full",
        hourly_rate=Decimal("100.0000"),
        premium_hours=Decimal("10"),
    ) == Decimal("0.00")


def test_gen_salaried_premiums_none_mode_returns_zero():
    assert pf.gen_salaried_premiums(
        salaried_premium_mode="none",
        hourly_rate=Decimal("100.0000"),
        premium_hours=Decimal("10"),
    ) == Decimal("0.00")


def test_gen_salaried_premiums_hourly_equivalent():
    # 100.00/h * 10h * 1.50 = 1500.00
    assert pf.gen_salaried_premiums(
        salaried_premium_mode="hourly_equivalent",
        hourly_rate=Decimal("100.0000"),
        premium_hours=Decimal("10"),
        premium_multiplier=Decimal("1.50"),
    ) == Decimal("1500.00")


def test_gen_salaried_premiums_requires_multiplier():
    with pytest.raises(ValueError, match="premium_multiplier"):
        pf.gen_salaried_premiums(
            salaried_premium_mode="hourly_equivalent",
            hourly_rate=Decimal("100.0000"),
            premium_hours=Decimal("10"),
        )


def test_gen_salaried_premiums_unknown_mode_raises():
    with pytest.raises(ValueError, match="unknown salaried_premium_mode"):
        pf.gen_salaried_premiums(
            salaried_premium_mode="mystery",
            hourly_rate=Decimal("100.0000"),
            premium_hours=Decimal("10"),
        )


# ---------------------------------------------------------------------------
# gen_paid_leave
# ---------------------------------------------------------------------------

def test_gen_paid_leave_basic():
    # 800 * 5 = 4000.00
    assert pf.gen_paid_leave(
        daily_rate=Decimal("800.00"), paid_leave_days=Decimal("5"),
    ) == Decimal("4000.00")


# ---------------------------------------------------------------------------
# gen_public_holiday_unworked
# ---------------------------------------------------------------------------

def test_gen_public_holiday_unworked_basic():
    # 800 * 2 days * 1.0 = 1600.00 (multiplier from caller)
    assert pf.gen_public_holiday_unworked(
        daily_rate=Decimal("800.00"),
        holiday_days=Decimal("2"),
        public_holiday_pay_multiplier=Decimal("1.00"),
    ) == Decimal("1600.00")


def test_gen_public_holiday_unworked_requires_multiplier():
    with pytest.raises(ValueError, match="public_holiday_pay_multiplier"):
        pf.gen_public_holiday_unworked(
            daily_rate=Decimal("800.00"),
            holiday_days=Decimal("2"),
        )


# ---------------------------------------------------------------------------
# hourly_rate_from_monthly
# ---------------------------------------------------------------------------

def test_hourly_rate_from_monthly_40h_week():
    # 40 * 52 / 12 = 173.3333... monthly_hours
    # 20000.00 / 173.3333... = 115.3846153...  -> 115.3846 at 4 dp half-up
    result = pf.hourly_rate_from_monthly(
        monthly_salary=Decimal("20000.00"),
        contracted_weekly_hours=Decimal("40"),
    )
    assert result == Decimal("115.3846")


def test_hourly_rate_from_monthly_45h_week():
    # 45 * 52 / 12 = 195.0 exactly
    # 20000 / 195 = 102.5641025...  -> 102.5641 at 4 dp half-up
    result = pf.hourly_rate_from_monthly(
        monthly_salary=Decimal("20000.00"),
        contracted_weekly_hours=Decimal("45"),
    )
    assert result == Decimal("102.5641")


def test_hourly_rate_from_monthly_zero_hours_raises():
    with pytest.raises(ValueError, match="positive"):
        pf.hourly_rate_from_monthly(
            monthly_salary=Decimal("20000.00"),
            contracted_weekly_hours=Decimal("0"),
        )

# END OF FILE
