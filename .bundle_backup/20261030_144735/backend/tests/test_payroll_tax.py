"""Tax engine tests (Chapter 4, Bundle 004a-ii).

Every expected figure is hand-worked in the comment above the assertion.
The brackets/rebates/thresholds/credits used are from the SYNTHETIC
fixture (fake_tax_tables.json), never real SA values.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.services import payroll_refusals as R
from app.services import payroll_tax as T


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_compute_age_simple():
    assert T.compute_age(date(1990, 5, 15), date(2025, 5, 15)) == 35


def test_compute_age_before_birthday():
    # 2025-04-30 is before 1990-05-15, so age is still 34
    assert T.compute_age(date(1990, 5, 15), date(2025, 4, 30)) == 34


def test_compute_age_on_birthday_65():
    # age 65 reached exactly on 2025-05-15
    assert T.compute_age(date(1960, 5, 15), date(2025, 5, 15)) == 65


# ---------------------------------------------------------------------------
# Bracket math (fake brackets: [0,1000)@10%, [1000,2000)@15%, [2000,null)@20%)
# ---------------------------------------------------------------------------

FAKE_BRACKETS = [
    {"row_key": "1", "lower_bound": "0", "upper_bound": "1000", "rate": "0.10", "base_tax": "0"},
    {"row_key": "2", "lower_bound": "1000", "upper_bound": "2000", "rate": "0.15", "base_tax": "100"},
    {"row_key": "3", "lower_bound": "2000", "upper_bound": None, "rate": "0.20", "base_tax": "250"},
]


def test_apply_brackets_below_first():
    # annual_taxable = 0 -> tax 0
    total, trace = T._apply_brackets(Decimal(0), FAKE_BRACKETS)
    assert total == Decimal(0)
    assert trace == []


def test_apply_brackets_within_first():
    # taxable = 500 -> 500 * 0.10 = 50.00
    total, trace = T._apply_brackets(Decimal(500), FAKE_BRACKETS)
    assert total == Decimal("50.00")
    assert len(trace) == 1 and trace[0].row_key == "1"


def test_apply_brackets_spanning_two():
    # taxable = 1500 -> 1000*0.10 + 500*0.15 = 100 + 75 = 175.00
    total, trace = T._apply_brackets(Decimal(1500), FAKE_BRACKETS)
    assert total == Decimal("175.00")
    assert len(trace) == 2


def test_apply_brackets_top_bracket_open_ended():
    # taxable = 12000 -> 100 + 150 + (12000-2000)*0.20 = 100 + 150 + 2000 = 2250.00
    total, trace = T._apply_brackets(Decimal(12000), FAKE_BRACKETS)
    assert total == Decimal("2250.00")
    assert len(trace) == 3
    assert trace[2].taxable_in_bracket == Decimal(10000)


# ---------------------------------------------------------------------------
# Rebates
# ---------------------------------------------------------------------------

FAKE_REBATES = {
    "primary": Decimal(100),
    "secondary_65": Decimal(50),
    "tertiary_75": Decimal(25),
}


def test_rebates_under_65():
    assert T._rebates_for_age(40, FAKE_REBATES) == Decimal(100)


def test_rebates_65_to_74():
    assert T._rebates_for_age(65, FAKE_REBATES) == Decimal(150)


def test_rebates_75_plus():
    assert T._rebates_for_age(80, FAKE_REBATES) == Decimal(175)


# ---------------------------------------------------------------------------
# Medical credits (monthly * 12; fake amounts 10 first, 5 additional)
# ---------------------------------------------------------------------------

FAKE_CREDITS = {
    "first_member": Decimal(10),
    "additional_member": Decimal(5),
    "first_dependant": Decimal(5),
}


def test_credits_zero_members():
    assert T._credits_for_members(0, FAKE_CREDITS) == Decimal(0)


def test_credits_one_member():
    # 10 * 12 = 120
    assert T._credits_for_members(1, FAKE_CREDITS) == Decimal(120)


def test_credits_two_members():
    # (10 + 5) * 12 = 180
    assert T._credits_for_members(2, FAKE_CREDITS) == Decimal(180)


def test_credits_three_members():
    # (10 + 5*2) * 12 = 240
    assert T._credits_for_members(3, FAKE_CREDITS) == Decimal(240)


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

FAKE_THRESHOLDS = {
    "below_age_65": Decimal(500),
    "age_65_to_74": Decimal(400),
    "age_75_plus": Decimal(300),
}


def test_threshold_under_65():
    assert T._threshold_for_age(40, FAKE_THRESHOLDS) == Decimal(500)


def test_threshold_65_to_74():
    assert T._threshold_for_age(65, FAKE_THRESHOLDS) == Decimal(400)


def test_threshold_75_plus():
    assert T._threshold_for_age(80, FAKE_THRESHOLDS) == Decimal(300)


# ---------------------------------------------------------------------------
# Full TaxEngine.compute
# ---------------------------------------------------------------------------

def _tables():
    return T.TaxTables(
        brackets=FAKE_BRACKETS,
        rebates=FAKE_REBATES,
        thresholds=FAKE_THRESHOLDS,
        medical_credits=FAKE_CREDITS,
        retirement_limit={"percentage_of_taxable_income": Decimal("0.10"), "annual_cap": Decimal(1000)},
        source_version="synthetic_fake_v1",
    )


def test_compute_below_threshold_paye_zero():
    # taxable 40/month * 12 = 480 annual, below 500 threshold -> PAYE 0
    engine = T.RegularEarningsTaxEngine()
    r = engine.compute(
        taxable_income=Decimal(40),
        pay_periods_per_year=12,
        employee_age=40,
        medical_members=0,
        tables=_tables(),
    )
    assert r.period_paye == Decimal("0.00")
    assert r.annual_tax == Decimal(0)


def test_compute_above_threshold_no_rebates_effect():
    # annual_taxable 12000, brackets = 2250
    # rebates 100, credits 0 -> annual tax 2150
    # per month = 2150/12 = 179.1666 -> 179.17 half-up
    engine = T.RegularEarningsTaxEngine()
    r = engine.compute(
        taxable_income=Decimal(1000),  # 1000 * 12 = 12000
        pay_periods_per_year=12,
        employee_age=40,
        medical_members=0,
        tables=_tables(),
    )
    assert r.annual_taxable == Decimal(12000)
    assert r.bracket_tax == Decimal("2250.00")
    assert r.rebates_total == Decimal(100)
    assert r.credits_total == Decimal(0)
    assert r.annual_tax == Decimal(2150)
    assert r.period_paye == Decimal("179.17")


def test_compute_with_65_rebate_and_medical():
    # annual_taxable 12000, brackets 2250
    # rebate (primary + secondary_65) = 150
    # medical 2 members = 180
    # annual = 2250 - 150 - 180 = 1920
    # per month = 160.00
    engine = T.RegularEarningsTaxEngine()
    r = engine.compute(
        taxable_income=Decimal(1000),
        pay_periods_per_year=12,
        employee_age=65,
        medical_members=2,
        tables=_tables(),
    )
    assert r.rebates_total == Decimal(150)
    assert r.credits_total == Decimal(180)
    assert r.annual_tax == Decimal(1920)
    assert r.period_paye == Decimal("160.00")


def test_compute_trace_records_brackets():
    engine = T.RegularEarningsTaxEngine()
    r = engine.compute(
        taxable_income=Decimal(1000),
        pay_periods_per_year=12,
        employee_age=40,
        medical_members=0,
        tables=_tables(),
    )
    assert len(r.trace) == 3
    dicts = r.trace_dicts()
    assert dicts[0]["row_key"] == "1"
    assert dicts[2]["taxable_in_bracket"] == "10000"


def test_compute_rejects_non_positive_periods():
    engine = T.RegularEarningsTaxEngine()
    with pytest.raises(R.PayrollRefusal):
        engine.compute(
            taxable_income=Decimal(1000),
            pay_periods_per_year=0,
            employee_age=40,
            medical_members=0,
            tables=_tables(),
        )


def test_compute_rejects_negative_taxable():
    engine = T.RegularEarningsTaxEngine()
    with pytest.raises(R.PayrollRefusal):
        engine.compute(
            taxable_income=Decimal(-1),
            pay_periods_per_year=12,
            employee_age=40,
            medical_members=0,
            tables=_tables(),
        )


def test_default_engine_method():
    assert T.default_engine().method == T.TaxMethod.REGULAR_EARNINGS


def test_only_regular_earnings_method_available():
    assert T.is_method_available(T.TaxMethod.REGULAR_EARNINGS)
    assert len(T.AVAILABLE_TAX_METHODS) == 1


# ---------------------------------------------------------------------------
# Integration with fake statutory tables (control DB)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def seeded_control_tables():
    """Seed synthetic_fake_v1 tables into the control DB (ZA) with 2099 window."""
    import json
    from pathlib import Path
    from app.db.control.session import control_session
    from app.services import statutory_loader as sl

    fixtures_path = Path(__file__).resolve().parent / "fixtures" / "fake_tax_tables.json"
    data = json.loads(fixtures_path.read_text(encoding="utf-8"))

    with control_session() as s:
        engine = s.get_bind()
    sl.bootstrap_schema(engine)

    seeded_versions = []
    with engine.begin() as conn:
        # Clean any prior 2099-window rows for these types (idempotent across runs)
        for t in data["tables"]:
            conn.execute(
                __import__("sqlalchemy").text(
                    "DELETE FROM statutory_table WHERE country_code=:c AND table_type=:t "
                    "AND version=:v"
                ),
                {"c": t["country_code"], "t": t["table_type"], "v": t["version"]},
            )

    for t in data["tables"]:
        # Rebrand to 2099 window so no overlap with real ZA data
        doc = {k: v for k, v in t.items() if not k.startswith("_")}
        doc["effective_from"] = "2099-01-01"
        doc["effective_to"] = "2099-12-31"
        doc["version"] = "test_004a_ii_" + doc["table_type"]
        sl.apply_document(
            engine, doc,
            actor_user_id=None,
            typed_version=doc["version"],
        )
        seeded_versions.append((doc["country_code"], doc["table_type"], doc["version"]))

    yield engine

    # Cleanup
    with engine.begin() as conn:
        for cc, tt, v in seeded_versions:
            row = conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT id FROM statutory_table WHERE country_code=:c AND table_type=:t AND version=:v"
                ),
                {"c": cc, "t": tt, "v": v},
            ).first()
            if row:
                conn.execute(__import__("sqlalchemy").text(
                    "DELETE FROM statutory_table_row WHERE statutory_table_id=:id"
                ), {"id": row[0]})
                conn.execute(__import__("sqlalchemy").text(
                    "DELETE FROM statutory_table_load_log WHERE statutory_table_id=:id"
                ), {"id": row[0]})
                conn.execute(__import__("sqlalchemy").text(
                    "DELETE FROM statutory_table WHERE id=:id"
                ), {"id": row[0]})


def test_load_tax_tables_from_control_db(seeded_control_tables):
    engine = seeded_control_tables
    tables = T.load_tax_tables(engine, date(2099, 6, 1))
    assert tables.source_version == "test_004a_ii_tax_bracket"
    assert len(tables.brackets) == 3
    assert tables.rebates["primary"] == Decimal(100)
    assert tables.thresholds["below_age_65"] == Decimal(500)
    assert tables.medical_credits["first_member"] == Decimal(10)


def test_load_tax_tables_missing_on_date(seeded_control_tables):
    engine = seeded_control_tables
    with pytest.raises(R.PayrollRefusal) as exc_info:
        T.load_tax_tables(engine, date(2100, 6, 1))
    assert exc_info.value.code == R.STATUTORY_TABLE_MISSING


def test_end_to_end_engine_with_control_db(seeded_control_tables):
    engine = seeded_control_tables
    tables = T.load_tax_tables(engine, date(2099, 6, 1))
    result = T.RegularEarningsTaxEngine().compute(
        taxable_income=Decimal(1000),
        pay_periods_per_year=12,
        employee_age=40,
        medical_members=0,
        tables=tables,
    )
    assert result.annual_tax == Decimal(2150)
    assert result.period_paye == Decimal("179.17")

# END OF FILE
