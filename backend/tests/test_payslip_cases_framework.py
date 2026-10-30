"""Hand-worked payslip case framework (Chapter 4, Bundle 004b-c).

Loads every *.json in tests/data/payslip_cases/ except TEMPLATE.json, runs
each through the 8-step pipeline against the synthetic fake_tax_tables
fixture, and asserts against the case's expected values.

Adding a case = adding one JSON file. No code changes required.

Skips:
  - when no case files exist yet (only TEMPLATE.json)
  - individual cases whose expected.* values are all null (incomplete)
  - individual cases that the pipeline refuses with a bounded code

The reviewer (or the accountant) supplies hand-worked cases; the framework
verifies the pipeline matches human arithmetic on the synthetic fixture.
"""
from __future__ import annotations

import json
import pathlib
from decimal import Decimal

import pytest

from app.services import payroll_pipeline as P
from app.services import payroll_tax as T


CASES_DIR = pathlib.Path(__file__).resolve().parent / "data" / "payslip_cases"
FIXTURES_DIR = pathlib.Path(__file__).resolve().parent / "fixtures"


def _case_files() -> list[pathlib.Path]:
    if not CASES_DIR.is_dir():
        return []
    return sorted(
        f for f in CASES_DIR.glob("*.json") if f.name != "TEMPLATE.json"
    )


def _is_placeholder(case: dict) -> bool:
    exp = case.get("expected") or {}
    return all(v is None for v in exp.values())


def _load_fixture() -> dict:
    return json.loads((FIXTURES_DIR / "fake_tax_tables.json").read_text(encoding="utf-8"))


def _rows_of(fixture: dict, table_type: str) -> list[dict]:
    for t in fixture["tables"]:
        if t["table_type"] == table_type:
            return t["rows"]
    return []


def _tax_tables(fixture: dict) -> T.TaxTables:
    brackets = _rows_of(fixture, "tax_bracket")
    rebates = {r["row_key"]: Decimal(r["amount"]) for r in _rows_of(fixture, "tax_rebate")}
    thresholds = {r["row_key"]: Decimal(r["amount"]) for r in _rows_of(fixture, "tax_threshold")}
    credits = {r["row_key"]: Decimal(r["amount"]) for r in _rows_of(fixture, "medical_credit")}
    ret = {r["row_key"]: Decimal(r["value"]) for r in _rows_of(fixture, "retirement_limit")}
    return T.TaxTables(
        brackets=brackets,
        rebates=rebates,
        thresholds=thresholds,
        medical_credits=credits,
        retirement_limit=ret,
        source_version="synthetic_fake_v1",
    )


_case_paths = _case_files()
_params = _case_paths or [None]
_ids = [f.stem if f else "no_cases_yet" for f in _params]


@pytest.mark.parametrize("case_path", _params, ids=_ids)
def test_hand_worked_payslip(case_path):
    if case_path is None:
        pytest.skip(
            "no hand-worked payslip cases yet - add JSON files to "
            "tests/data/payslip_cases/ (copy TEMPLATE.json)"
        )
    case = json.loads(case_path.read_text(encoding="utf-8"))
    if _is_placeholder(case):
        pytest.skip(f"{case_path.name}: expected.* are placeholders")

    fixture = _load_fixture()
    employee = case.get("employee") or {}
    config = P.PipelineConfig(
        tax_engine=T.default_engine(),
        tax_tables=_tax_tables(fixture),
        uif_rows=_rows_of(fixture, "uif"),
        sdl_rows=_rows_of(fixture, "sdl"),
        retirement_rows=_rows_of(fixture, "retirement_limit"),
        periods_per_year=12,
        employee_age=int(employee.get("age_years") or 30),
        medical_members=int(employee.get("medical_scheme_members") or 0),
        uif_exempt=bool(employee.get("uif_exempt") or False),
        sdl_applies=True,
        net_pay_floor=Decimal("0.00"),
    )

    earnings: list[P.EarningLine] = []
    for e in case.get("earnings") or []:
        if e.get("amount") is None:
            continue
        earnings.append(P.EarningLine(
            label=e.get("label", "Earning"),
            amount=Decimal(str(e["amount"])),
        ))
    if not earnings:
        ms = employee.get("monthly_salary")
        if ms is not None:
            earnings = [P.EarningLine("Base", Decimal(str(ms)))]

    draft = P.run_pipeline(config, earnings, [], [])
    if draft.refused:
        pytest.skip(
            f"{case_path.name}: pipeline refused ({draft.refusal_code}); "
            f"case is not computable under v1 rules"
        )

    exp = case["expected"]

    def _cmp(field: str, actual: Decimal) -> None:
        if exp.get(field) is None:
            return
        expected = Decimal(str(exp[field]))
        assert actual == expected, (
            f"{case_path.name}: {field} mismatch "
            f"(expected {expected}, got {actual})"
        )

    _cmp("gross", draft.gross)
    _cmp("paye", draft.paye)
    _cmp("uif_employee", draft.uif_employee)
    _cmp("uif_employer", draft.uif_employer)
    _cmp("sdl", draft.sdl)
    _cmp("net", draft.net)

# END OF FILE
