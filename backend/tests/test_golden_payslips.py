"""Chapter 4H 4G-c: golden payslip case framework.

Unreviewed cases cause a loud `pytest.skip` naming each file
(round-2 §16 + amendment: never silently green). Reviewed cases run
the real preview pipeline against case fixtures and compare per-field
and per-line. Placeholder cases ship with `accountant_reviewed=false`
so this file is green before the accountant's cases arrive.

Statutory tables used by every case are fixed fake constants (see
README.md). Real ZA tables replace them when available as a test
fixture.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.attendance import (
    AttendanceDay,
    AttendanceSegment,
    Shift,
    ShiftRateRule,
)
from app.db.tenant.models.organisation import Company
from app.db.tenant.models.pay import (
    DeductionType,
    EarningType,
    EmployeeDeduction,
    EmployeeEarning,
    PayPeriod,
    Payslip,
    PayslipLine,
)
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.people import Employee, User
from app.services import payroll_tax as T
from app.services.payroll_runner import run_preview
from app.services.provisioning import (
    _drop_tenant_database,
    _tenant_db_name,
    provision_tenant,
)
from tests.golden_payslips._schema import GoldenPayslipCase


CASES_DIR = Path(__file__).parent / "golden_payslips"


_FAKE_UIF = [
    {"row_key": "employee_rate", "value": "0.01"},
    {"row_key": "employer_rate", "value": "0.01"},
    {"row_key": "monthly_ceiling", "value": "100000"},
]
_FAKE_SDL = [
    {"row_key": "rate", "value": "0.01"},
    {"row_key": "exemption_threshold_annual", "value": "50000"},
]
_FAKE_RETIREMENT = [
    {"row_key": "percentage_of_taxable_income", "value": "0.10"},
    {"row_key": "annual_cap", "value": "1000"},
]
_FAKE_BY_TYPE = {
    "uif": _FAKE_UIF,
    "sdl": _FAKE_SDL,
    "retirement_limit": _FAKE_RETIREMENT,
}


def _fake_load_control_table(table_type: str, on_date: date) -> list[dict]:
    return _FAKE_BY_TYPE[table_type]


def _fake_load_tax_tables(engine_or_session, on_date, country_code="ZA") -> T.TaxTables:
    return T.TaxTables(
        brackets=[
            {"row_key": "1", "lower_bound": "0", "upper_bound": "10000",
             "rate": "0.18", "base_tax": "0"},
        ],
        rebates={"primary": Decimal("1000"),
                 "secondary_65": Decimal("0"),
                 "tertiary_75": Decimal("0")},
        thresholds={"below_age_65": Decimal("5000"),
                    "age_65_to_74": Decimal("5000"),
                    "age_75_plus": Decimal("5000")},
        medical_credits={"first_member": Decimal("0"),
                         "additional_member": Decimal("0"),
                         "first_dependant": Decimal("0")},
        retirement_limit={"percentage_of_taxable_income": Decimal("0.10"),
                          "annual_cap": Decimal("100000")},
        source_version="golden-framework-fake",
    )


def _patch_statutory(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.payroll_runner._load_control_table",
        _fake_load_control_table,
    )
    monkeypatch.setattr(T, "load_tax_tables", _fake_load_tax_tables)


def _load_all_cases() -> list[tuple[Path, GoldenPayslipCase | None, Exception | None]]:
    loaded: list[tuple[Path, GoldenPayslipCase | None, Exception | None]] = []
    if not CASES_DIR.is_dir():
        return loaded
    for path in sorted(CASES_DIR.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            loaded.append((path, GoldenPayslipCase(**raw), None))
        except Exception as exc:
            loaded.append((path, None, exc))
    return loaded


def _diff_expected_vs_actual(expected: dict, actual: dict) -> list[str]:
    issues: list[str] = []

    for field in ("gross", "paye", "net"):
        exp = Decimal(str(expected[field]))
        got = actual[field]
        if exp != got:
            issues.append(f"{field}: expected {exp}, got {got}")

    exp_lines = sorted(
        (str(l.get("earning_type_code", "")), Decimal(str(l["amount"])))
        for l in expected.get("lines", [])
    )
    got_lines = sorted(
        (str(l.get("earning_type_code", "")), Decimal(str(l["amount"])))
        for l in actual.get("lines", [])
    )
    for exp_k, exp_amt in exp_lines:
        match = next((g for g in got_lines if g[0] == exp_k), None)
        if match is None:
            issues.append(f"line {exp_k}: missing in actual")
        elif match[1] != exp_amt:
            issues.append(f"line {exp_k}: expected {exp_amt}, got {match[1]}")

    exp_deds = sorted(
        (str(d.get("deduction_type_name", "")), Decimal(str(d["amount"])))
        for d in expected.get("deductions", [])
    )
    got_deds = sorted(
        (str(d.get("deduction_type_name", "")), Decimal(str(d["amount"])))
        for d in actual.get("deductions", [])
    )
    for exp_k, exp_amt in exp_deds:
        match = next((g for g in got_deds if g[0] == exp_k), None)
        if match is None:
            issues.append(f"deduction {exp_k}: missing in actual")
        elif match[1] != exp_amt:
            issues.append(f"deduction {exp_k}: expected {exp_amt}, got {match[1]}")

    return issues


def _apply_case_to_tenant(db: Session, case: GoldenPayslipCase):
    company = db.scalar(select(Company))
    if company is None:
        company = Company(
            legal_name=case.case_id,
            country_code="ZA",
            currency="ZAR",
            default_timezone="Africa/Johannesburg",
            settings={},
            row_version=1,
        )
        db.add(company)
    company.settings = {**(company.settings or {}), **(case.company_settings or {})}
    db.flush()

    ps = db.scalar(select(PayrollSettings))
    if ps is None:
        ps = PayrollSettings(
            id=uuid.uuid4(),
            age_reference_date=None,
            sdl_applies=None,
            net_pay_floor=Decimal("0"),
            formula_acks={},
            attendance_earning_map={},
            row_version=1,
        )
        db.add(ps)
    for k, v in (case.payroll_settings or {}).items():
        setattr(ps, k, v)
    db.flush()

    e = case.employee
    emp = Employee(
        employee_code=e["employee_code"],
        first_name=e["first_name"],
        last_name=e["last_name"],
        hire_date=date.fromisoformat(e["hire_date"]),
        status=e.get("status", "active"),
        employee_type=e.get("employee_type", "hourly"),
        pay_basis=e.get("pay_basis", "hourly"),
        pay_frequency=e.get("pay_frequency", "monthly"),
        base_rate=Decimal(str(e["base_rate"])) if e.get("base_rate") else None,
        contracted_weekly_hours=e.get("contracted_weekly_hours"),
        row_version=1,
    )
    db.add(emp)
    db.flush()

    shift_id = None
    if case.shift:
        sh = case.shift
        shift = Shift(
            name=sh["name"],
            start_time=datetime.strptime(sh["start_time"], "%H:%M").time(),
            length_minutes=sh["length_minutes"],
            unpaid_break_minutes=sh.get("unpaid_break_minutes", 0),
            paid_break_minutes=sh.get("paid_break_minutes", 0),
            grace_late_minutes=sh.get("grace_late_minutes", 0),
            grace_early_minutes=sh.get("grace_early_minutes", 0),
            rounding_minutes=sh.get("rounding_minutes", 0),
            rounding_mode=sh.get("rounding_mode", "nearest"),
            min_overtime_minutes=sh.get("min_overtime_minutes", 0),
            overtime_requires_approval=sh.get("overtime_requires_approval", False),
            max_shift_minutes=sh.get("max_shift_minutes", 720),
            match_tolerance_minutes=sh.get("match_tolerance_minutes", 60),
            salaried_premium_mode=sh.get("salaried_premium_mode", "full"),
            grace_mode=sh.get("grace_mode", "threshold"),
            pay_early_arrival=sh.get("pay_early_arrival", False),
            is_active=True,
            row_version=1,
        )
        db.add(shift)
        db.flush()
        shift_id = shift.id

    for r in case.shift_rate_rules or []:
        db.add(ShiftRateRule(
            shift_id=shift_id,
            day_type=r["day_type"],
            kind=r["kind"],
            tier=r.get("tier", 1),
            tier_up_to_minutes=r.get("tier_up_to_minutes"),
            method=r.get("method", "multiplier"),
            value=Decimal(str(r["value"])),
            flat_unit=r.get("flat_unit"),
            effective_from=date.fromisoformat(r.get("effective_from", "2024-01-01")),
            effective_to=(
                date.fromisoformat(r["effective_to"])
                if r.get("effective_to") else None
            ),
        ))
    db.flush()

    for ee in case.employee_earnings or []:
        et = db.scalar(select(EarningType).where(
            EarningType.code == ee["earning_type_code"]
        ))
        if et is None:
            raise RuntimeError(
                f"earning_type_code={ee['earning_type_code']!r} not found; "
                f"case must reference a code from SYSTEM_TYPES"
            )
        db.add(EmployeeEarning(
            id=uuid.uuid4(),
            employee_id=emp.id,
            earning_type_id=et.id,
            amount=Decimal(str(ee["amount"])) if ee.get("amount") else None,
            rate=Decimal(str(ee["rate"])) if ee.get("rate") else None,
            effective_from=date.fromisoformat(ee["effective_from"]),
            effective_to=(
                date.fromisoformat(ee["effective_to"])
                if ee.get("effective_to") else None
            ),
            is_active=True,
            row_version=1,
        ))
    db.flush()

    for ed in case.employee_deductions or []:
        dt = db.scalar(select(DeductionType).where(
            DeductionType.code == ed["deduction_type_code"]
        ))
        if dt is None:
            dt = DeductionType(
                id=uuid.uuid4(),
                name=ed["deduction_type_code"].replace("_", " ").title(),
                code=ed["deduction_type_code"],
                category=ed.get("category", "other"),
                priority=ed.get("priority", 100),
                is_pre_tax=ed.get("is_pre_tax", False),
                is_system=False,
                is_active=True,
                row_version=1,
            )
            db.add(dt)
            db.flush()
        db.add(EmployeeDeduction(
            id=uuid.uuid4(),
            employee_id=emp.id,
            deduction_type_id=dt.id,
            amount=Decimal(str(ed["amount"])),
            balance=Decimal("0"),
            effective_from=date.fromisoformat(ed["effective_from"]),
            effective_to=(
                date.fromisoformat(ed["effective_to"])
                if ed.get("effective_to") else None
            ),
            is_active=True,
            row_version=1,
        ))
    db.flush()

    day_by_date = {}
    for ad in case.attendance_days or []:
        wd = date.fromisoformat(ad["work_date"])
        day = AttendanceDay(
            id=uuid.uuid4(),
            employee_id=emp.id,
            work_date=wd,
            status=ad.get("status", "present"),
            shift_id=shift_id,
            worked_minutes=ad.get("worked_minutes", 0),
            normal_minutes=ad.get("normal_minutes", 0),
            overtime_minutes=ad.get("overtime_minutes", 0),
            raw_minutes=ad.get("raw_minutes", 0),
            flags=ad.get("flags", []),
            source_version=0,
            locked=ad.get("locked", False),
            row_version=1,
            computed_at=datetime.now(timezone.utc),
        )
        db.add(day)
        db.flush()
        day_by_date[wd.isoformat()] = day

    for seg in case.attendance_segments or []:
        ld = seg["local_date"]
        day = day_by_date.get(ld)
        if day is None:
            raise RuntimeError(
                f"attendance_segment local_date={ld!r} has no matching "
                f"attendance_day in this case"
            )
        db.add(AttendanceSegment(
            id=uuid.uuid4(),
            attendance_day_id=day.id,
            local_date=date.fromisoformat(ld),
            day_type=seg["day_type"],
            kind=seg["kind"],
            tier=seg.get("tier", 1),
            minutes=seg["minutes"],
            rate_method=seg.get("rate_method", "multiplier"),
            rate_value=Decimal(str(seg["rate_value"])),
            overtime_status=seg.get("overtime_status"),
            source_refs=[],
        ))
    db.flush()

    pp = case.pay_period
    period = PayPeriod(
        id=uuid.uuid4(),
        period_key=pp["period_key"],
        start_date=date.fromisoformat(pp["start_date"]),
        end_date=date.fromisoformat(pp["end_date"]),
        pay_date=date.fromisoformat(pp["pay_date"]),
        status="open",
        cutoff_at=datetime.fromisoformat(
            pp.get("cutoff_at", f"{pp['end_date']}T23:59:00+00:00")
        ),
    )
    db.add(period)
    db.flush()

    return emp, period


def _run_case(path: Path, case: GoldenPayslipCase) -> list[str]:
    slug = f"golden-{uuid.uuid4().hex[:8]}"
    result = provision_tenant(
        slug=slug,
        name=f"Golden {case.case_id}",
        admin_username="admin",
        admin_password_hash=hash_password("AdminPassword123!"),
    )
    db_url = (
        "postgresql+psycopg://payroll_app:payroll_app_dev_password"
        f"@localhost:5432/{result.tenant_db_name}"
    )
    engine = create_engine(db_url, future=True)
    try:
        with Session(engine) as db:
            emp, period = _apply_case_to_tenant(db, case)
            admin = db.scalar(select(User).where(User.username == "admin"))
            run = run_preview(db, admin, period)
            db.commit()

            ps = db.scalar(select(Payslip).where(
                Payslip.payroll_run_id == run.id,
                Payslip.employee_id == emp.id,
            ))
            if ps is None:
                return [f"no payslip generated for employee {emp.employee_code}"]

            line_rows = list(db.scalars(select(PayslipLine).where(
                PayslipLine.payslip_id == ps.id
            )).all())

            actual = {
                "gross": ps.gross,
                "paye": ps.paye,
                "net": ps.net,
                "lines": [
                    {
                        "earning_type_code": (l.source_ref or {}).get("earning_type_code", ""),
                        "amount": l.amount,
                    }
                    for l in line_rows if l.line_type == "earning"
                ],
                "deductions": [
                    {
                        "deduction_type_name": l.label,
                        "amount": l.amount,
                    }
                    for l in line_rows
                    if l.line_type == "deduction"
                    and not (l.source_ref or {}).get("deferred")
                ],
            }
            return _diff_expected_vs_actual(case.expected.model_dump(), actual)
    finally:
        engine.dispose()
        _drop_tenant_database(result.tenant_db_name)
        with control_session() as s:
            r = s.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if r is not None:
                s.delete(r)


def test_golden_loader_reads_all_json():
    cases = _load_all_cases()
    valid = [c for _, c, _ in cases if c is not None]
    assert len(valid) >= 2, (
        f"expected at least 2 placeholder cases under {CASES_DIR}, "
        f"found {len(valid)}"
    )


def test_golden_loader_captures_invalid_schema_without_crashing():
    cases = _load_all_cases()
    for path, case, exc in cases:
        assert (case is None) != (exc is None), (
            f"{path.name}: loader must set exactly one of case/exception"
        )


def test_golden_reviewed_case_requires_reviewer_fields():
    base = {
        "case_id": "t1",
        "description": "d",
        "accountant_reviewed": True,
        "employee": {},
        "pay_period": {},
        "expected": {"gross": "0", "paye": "0", "net": "0"},
    }
    with pytest.raises(ValidationError):
        GoldenPayslipCase(**base)
    with pytest.raises(ValidationError):
        GoldenPayslipCase(**{**base, "reviewed_by": "x"})
    case = GoldenPayslipCase(**{
        **base,
        "reviewed_by": "acc@example.com",
        "reviewed_on": "2026-01-15",
    })
    assert case.reviewed_by == "acc@example.com"
    assert case.reviewed_on == "2026-01-15"


def test_golden_runner_per_line_comparison():
    expected = {
        "gross": "100.00", "paye": "10.00", "net": "90.00",
        "lines": [
            {"earning_type_code": "hourly_normal", "amount": "100.00"}
        ],
        "deductions": [
            {"deduction_type_name": "PAYE", "amount": "10.00"}
        ],
    }
    actual = {
        "gross": Decimal("100.00"),
        "paye": Decimal("10.00"),
        "net": Decimal("90.00"),
        "lines": [
            {"earning_type_code": "hourly_normal", "amount": Decimal("100.00")}
        ],
        "deductions": [
            {"deduction_type_name": "PAYE", "amount": Decimal("10.00")}
        ],
    }
    assert _diff_expected_vs_actual(expected, actual) == []

    bad_gross = {**actual, "gross": Decimal("99.00")}
    diffs = _diff_expected_vs_actual(expected, bad_gross)
    assert any("gross" in d for d in diffs)

    bad_line = {**actual, "lines": [
        {"earning_type_code": "hourly_normal", "amount": Decimal("99.00")}
    ]}
    diffs = _diff_expected_vs_actual(expected, bad_line)
    assert any("line hourly_normal" in d for d in diffs)


def test_golden_unreviewed_cases_skipped_loudly():
    cases = _load_all_cases()
    unreviewed = [p.name for p, c, _ in cases if c is not None and not c.accountant_reviewed]
    if not unreviewed:
        return
    pytest.skip(
        f"{len(unreviewed)} unreviewed golden case(s) pending accountant: "
        f"{unreviewed} — see docs/STATE.md 'Payroll golden cases'"
    )


def test_golden_reviewed_cases_pass(monkeypatch):
    cases = _load_all_cases()
    reviewed = [
        (p, c) for p, c, _ in cases
        if c is not None and c.accountant_reviewed
    ]
    if not reviewed:
        pytest.skip(
            "0 reviewed golden case(s); accountant has not yet signed off. "
            "See docs/STATE.md 'Payroll golden cases'"
        )

    _patch_statutory(monkeypatch)

    failures: list[tuple[str, list[str]]] = []
    for path, case in reviewed:
        try:
            diff = _run_case(path, case)
            if diff:
                failures.append((path.name, diff))
        except Exception as exc:
            failures.append((path.name, [f"exception: {exc!r}"]))
    if failures:
        msg = "\n".join(
            f"{name}:\n  " + "\n  ".join(d) for name, d in failures
        )
        pytest.fail(msg)