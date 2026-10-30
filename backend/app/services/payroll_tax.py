"""Tax engine (Chapter 4, Bundle 004a-ii).

Computes PAYE for a single employee, single pay period, using the
effective-dated statutory tables loaded from the control database.

Method v1: REGULAR_EARNINGS only. Assumes the employee works the whole
year at the current period's taxable income. Once-off / irregular taxable
earnings break that assumption (annualising a one-time payment massively
over-withholds) and are REFUSED by the pipeline in 004a-iii; the engine
exposes TaxMethod so the pipeline can enforce that.

Rounding: two decimals, half-up, applied once at the final division.
Intermediate tax calculations use unrounded Decimal.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any

from app.services import payroll_refusals as R


# ---------------------------------------------------------------------------
# Method registry
# ---------------------------------------------------------------------------

class TaxMethod(str, Enum):
    REGULAR_EARNINGS = "regular_earnings_v1"


AVAILABLE_TAX_METHODS: frozenset[TaxMethod] = frozenset({TaxMethod.REGULAR_EARNINGS})

DEFAULT_TAX_METHOD: TaxMethod = TaxMethod.REGULAR_EARNINGS


def is_method_available(method: TaxMethod) -> bool:
    return method in AVAILABLE_TAX_METHODS


# ---------------------------------------------------------------------------
# Tables + result
# ---------------------------------------------------------------------------

@dataclass
class TaxTables:
    brackets: list[dict[str, Any]]
    rebates: dict[str, Decimal]
    thresholds: dict[str, Decimal]
    medical_credits: dict[str, Decimal]
    retirement_limit: dict[str, Decimal]
    source_version: str


@dataclass
class BracketTraceEntry:
    row_key: str
    lower_bound: Decimal
    upper_bound: Decimal | None
    rate: Decimal
    taxable_in_bracket: Decimal
    tax_amount: Decimal


@dataclass
class TaxResult:
    method: str
    period_paye: Decimal
    annual_taxable: Decimal
    threshold_applied: Decimal
    bracket_tax: Decimal
    rebates_total: Decimal
    credits_total: Decimal
    annual_tax: Decimal
    trace: list[BracketTraceEntry] = field(default_factory=list)

    def trace_dicts(self) -> list[dict[str, str]]:
        return [
            {
                "row_key": t.row_key,
                "lower_bound": str(t.lower_bound),
                "upper_bound": "" if t.upper_bound is None else str(t.upper_bound),
                "rate": str(t.rate),
                "taxable_in_bracket": str(t.taxable_in_bracket),
                "tax_amount": str(t.tax_amount),
            }
            for t in self.trace
        ]


# ---------------------------------------------------------------------------
# Helpers (pure)
# ---------------------------------------------------------------------------

def compute_age(date_of_birth: date, on_date: date) -> int:
    age = on_date.year - date_of_birth.year
    if (on_date.month, on_date.day) < (date_of_birth.month, date_of_birth.day):
        age -= 1
    return age


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _value_of(row: dict) -> Decimal:
    if "amount" in row:
        return _decimal(row["amount"])
    if "value" in row:
        return _decimal(row["value"])
    raise R.PayrollRefusal(
        R.STATUTORY_TABLE_INVALID,
        f"statutory row {row.get('row_key')!r} has neither 'amount' nor 'value'",
        500,
    )


def _rows_by_key(rows: list[dict]) -> dict[str, Decimal]:
    return {row["row_key"]: _value_of(row) for row in rows}


def _threshold_for_age(age: int, thresholds: dict[str, Decimal]) -> Decimal:
    if age >= 75:
        return thresholds.get("age_75_plus", thresholds.get("below_age_65", Decimal(0)))
    if age >= 65:
        return thresholds.get("age_65_to_74", thresholds.get("below_age_65", Decimal(0)))
    return thresholds.get("below_age_65", Decimal(0))


def _rebates_for_age(age: int, rebates: dict[str, Decimal]) -> Decimal:
    total = rebates.get("primary", Decimal(0))
    if age >= 65:
        total += rebates.get("secondary_65", Decimal(0))
    if age >= 75:
        total += rebates.get("tertiary_75", Decimal(0))
    return total


def _credits_for_members(members: int, credits: dict[str, Decimal]) -> Decimal:
    """Annual credit = (first_member + additional_member * (members-1)) * 12.

    Table values are MONTHLY per SARS convention (E5). Zero members -> zero.
    Part-year employment pro-rating is deferred (E5 note).
    """
    if members <= 0:
        return Decimal(0)
    first = credits.get("first_member", Decimal(0))
    additional = credits.get("additional_member", Decimal(0))
    monthly = first + additional * Decimal(members - 1)
    return monthly * Decimal(12)


def _apply_brackets(
    annual_taxable: Decimal, brackets: list[dict[str, Any]]
) -> tuple[Decimal, list[BracketTraceEntry]]:
    total = Decimal(0)
    trace: list[BracketTraceEntry] = []
    for row in brackets:
        lower = _decimal(row["lower_bound"])
        upper = None if row.get("upper_bound") is None else _decimal(row["upper_bound"])
        rate = _decimal(row["rate"])
        if upper is None:
            taxable = max(Decimal(0), annual_taxable - lower)
        else:
            taxable = max(Decimal(0), min(annual_taxable, upper) - lower)
        tax = taxable * rate
        if taxable > 0:
            trace.append(
                BracketTraceEntry(
                    row_key=row["row_key"],
                    lower_bound=lower,
                    upper_bound=upper,
                    rate=rate,
                    taxable_in_bracket=taxable,
                    tax_amount=tax,
                )
            )
        total += tax
    return total, trace


# ---------------------------------------------------------------------------
# Table loading
# ---------------------------------------------------------------------------

def _resolve_engine(engine_or_session: Any) -> Any:
    """Accept Engine, Connection, or Session; return something with .connect()."""
    if hasattr(engine_or_session, "connect"):
        return engine_or_session
    bind = engine_or_session.get_bind()
    if hasattr(bind, "connect"):
        return bind
    return bind.engine


def load_tax_tables(
    engine_or_session: Any,
    on_date: date,
    country_code: str = "ZA",
) -> TaxTables:
    """Load every statutory table needed for PAYE, effective on `on_date`."""
    from app.services.statutory_loader import get_active_table

    engine = _resolve_engine(engine_or_session)

    def fetch(table_type: str) -> dict:
        row = get_active_table(engine, country_code, table_type, on_date)
        if row is None:
            raise R.PayrollRefusal(
                R.STATUTORY_TABLE_MISSING,
                f"{country_code}/{table_type} has no active version covering {on_date.isoformat()}",
                409,
            )
        return row

    bracket_t = fetch("tax_bracket")
    rebate_t = fetch("tax_rebate")
    threshold_t = fetch("tax_threshold")
    credit_t = fetch("medical_credit")
    retirement_t = fetch("retirement_limit")

    return TaxTables(
        brackets=bracket_t["rows"],
        rebates=_rows_by_key(rebate_t["rows"]),
        thresholds=_rows_by_key(threshold_t["rows"]),
        medical_credits=_rows_by_key(credit_t["rows"]),
        retirement_limit=_rows_by_key(retirement_t["rows"]),
        source_version=bracket_t["version"],
    )


# ---------------------------------------------------------------------------
# Engine ABC + v1 implementation
# ---------------------------------------------------------------------------

class TaxEngine(ABC):
    method: TaxMethod

    @abstractmethod
    def compute(
        self,
        *,
        taxable_income: Decimal,
        pay_periods_per_year: int,
        employee_age: int,
        medical_members: int,
        tables: TaxTables,
    ) -> TaxResult: ...


class RegularEarningsTaxEngine(TaxEngine):
    method = TaxMethod.REGULAR_EARNINGS

    def compute(
        self,
        *,
        taxable_income: Decimal,
        pay_periods_per_year: int,
        employee_age: int,
        medical_members: int,
        tables: TaxTables,
    ) -> TaxResult:
        if pay_periods_per_year <= 0:
            raise R.PayrollRefusal(
                R.STATUTORY_TABLE_INVALID,
                "pay_periods_per_year must be positive",
                500,
            )
        if taxable_income < 0:
            raise R.PayrollRefusal(
                R.STATUTORY_TABLE_INVALID,
                "taxable_income must be non-negative",
                500,
            )

        annual_taxable = taxable_income * Decimal(pay_periods_per_year)
        threshold = _threshold_for_age(employee_age, tables.thresholds)

        if annual_taxable <= threshold:
            return TaxResult(
                method=self.method.value,
                period_paye=Decimal("0.00"),
                annual_taxable=annual_taxable,
                threshold_applied=threshold,
                bracket_tax=Decimal(0),
                rebates_total=Decimal(0),
                credits_total=Decimal(0),
                annual_tax=Decimal(0),
                trace=[],
            )

        bracket_tax, trace = _apply_brackets(annual_taxable, tables.brackets)
        rebates = _rebates_for_age(employee_age, tables.rebates)
        credits = _credits_for_members(medical_members, tables.medical_credits)
        annual_tax = max(Decimal(0), bracket_tax - rebates - credits)

        period_paye = (annual_tax / Decimal(pay_periods_per_year)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        return TaxResult(
            method=self.method.value,
            period_paye=period_paye,
            annual_taxable=annual_taxable,
            threshold_applied=threshold,
            bracket_tax=bracket_tax,
            rebates_total=rebates,
            credits_total=credits,
            annual_tax=annual_tax,
            trace=trace,
        )


def default_engine() -> TaxEngine:
    return RegularEarningsTaxEngine()

# END OF FILE
