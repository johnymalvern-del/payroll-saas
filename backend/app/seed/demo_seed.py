"""Demo seed for tenant-demo (B-2 + Chapter 4H B-4).

Refuses when environment in ("staging", "production").

Deferred (recorded in docs/SEED.md / STATE.md):
  - Fake statutory fixture load into control DB.
  - Demo PDF watermark (needs payroll_pdf.py source).
  - provision_tenant auto-seed hook (needs provisioning.py source).
"""
from __future__ import annotations

import argparse
import secrets
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.api.v1.attendance_engine import (
    _persist_adjustment,
    ensure_days,
    recompute_day,
)
from app.api.v1.device_auth import hash_device_key
from app.api.v1.punches import _process_punch
from app.api.v1.punches_schemas import PunchIn
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.attendance import (
    AttendanceDay,
    CountryCalendar,
    EmployeeWorkPattern,
    ExceptionItem,
    Shift,
    ShiftRateRule,
    WorkPattern,
    WorkPatternDay,
)
from app.db.tenant.models.devices import Device
from app.db.tenant.models.organisation import Branch, Company, Department, Site
from app.db.tenant.models.people import Employee, User
from app.db.tenant.models.pay import PayPeriod
from app.db.tenant.session import tenant_session
from app.services.payroll_change_request import (
    approve_change_request,
    submit_change_request,
)
from app.services.provisioning import (
    _drop_tenant_database,
    _tenant_db_name,
    provision_tenant,
)


SLUG = "tenant-demo"
SITE_TZ = "Africa/Johannesburg"
DEV_PASSWORD_PREFIX = "devpass_"

NAMES: list[tuple[str, str]] = [
    ("Ada", "Mokoena"),
    ("Sipho", "Dlamini"),
    ("Naledi", "Khumalo"),
    ("Thabo", "Mahlangu"),
    ("Lerato", "Sithole"),
    ("Kagiso", "Motaung"),
    ("Nomvula", "Zulu"),
    ("Bongani", "Nkosi"),
    ("Zanele", "Mabaso"),
    ("Sibusiso", "Mthembu"),
    ("Palesa", "Mokoena"),
    ("Tshepo", "Radebe"),
    ("Refilwe", "Mahlangu"),
    ("Mpho", "Ndlovu"),
    ("Karabo", "Motaung"),
    ("Ntombi", "Khumalo"),
    ("Lindani", "Zwane"),
    ("Kelebogile", "Dlamini"),
    ("Andile", "Sithole"),
    ("Amahle", "Nkosi"),
]

ROLES_EXTRA = [
    ("hr", "hr"),
    ("manager", "manager"),
    ("auditor", "auditor"),
    ("employee", "employee"),
]

_FIXED_ZA_HOLIDAYS = [
    ((1, 1), "New Year's Day"),
    ((3, 21), "Human Rights Day"),
    ((4, 27), "Freedom Day"),
    ((5, 1), "Workers' Day"),
    ((6, 16), "Youth Day"),
    ((8, 9), "National Women's Day"),
    ((9, 24), "Heritage Day"),
    ((12, 16), "Day of Reconciliation"),
    ((12, 25), "Christmas Day"),
    ((12, 26), "Day of Goodwill"),
]

# DEMO PLACEHOLDER multipliers (round-1 §5: not real payroll policy; flagged
# here and in docs/SEED.md). Real tenants must set their own shift_rate_rule
# rows through the shift-rate-rule API, based on accountant guidance.
_DEMO_RATE_RULES: list[dict] = [
    {"day_type": "weekday", "kind": "normal", "tier": 1, "method": "multiplier", "value": "1.0"},
    {"day_type": "saturday", "kind": "normal", "tier": 1, "method": "multiplier", "value": "1.5"},
    {"day_type": "sunday", "kind": "normal", "tier": 1, "method": "multiplier", "value": "2.0"},
    {"day_type": "public_holiday", "kind": "normal", "tier": 1, "method": "multiplier", "value": "2.0"},
    {"day_type": "weekday", "kind": "overtime", "tier": 1, "method": "multiplier", "value": "1.5"},
    {"day_type": "weekday", "kind": "overtime", "tier": 2, "method": "multiplier", "value": "2.0"},
    {"day_type": "weekday", "kind": "overtime", "tier": 3, "method": "multiplier", "value": "3.0"},
    {"day_type": "saturday", "kind": "overtime", "tier": 1, "method": "multiplier", "value": "2.0"},
    {"day_type": "saturday", "kind": "overtime", "tier": 2, "method": "multiplier", "value": "2.5"},
    {"day_type": "sunday", "kind": "overtime", "tier": 1, "method": "multiplier", "value": "2.5"},
    {"day_type": "public_holiday", "kind": "overtime", "tier": 1, "method": "multiplier", "value": "3.0"},
]


def _tz() -> ZoneInfo:
    return ZoneInfo(SITE_TZ)


def _local(date_obj: date, hh: int, mm: int) -> datetime:
    return datetime.combine(date_obj, time(hh, mm), tzinfo=_tz())


def _utc(date_obj: date, hh: int, mm: int) -> datetime:
    return _local(date_obj, hh, mm).astimezone(timezone.utc)


def _slug_exists() -> bool:
    with control_session() as s:
        row = s.query(Subscriber).filter(Subscriber.slug == SLUG).one_or_none()
        return row is not None


def _drop_tenant_and_subscriber() -> None:
    db_name = _tenant_db_name(SLUG)
    _drop_tenant_database(db_name)
    with control_session() as s:
        row = s.query(Subscriber).filter(Subscriber.slug == SLUG).one_or_none()
        if row is not None:
            s.delete(row)


def _punch(
    db,
    device: Device,
    employee_id: uuid.UUID,
    when_utc: datetime,
    *,
    device_now: datetime | None = None,
    match_score=None,
    liveness=None,
) -> None:
    payload = PunchIn(
        client_punch_id=uuid.uuid4(),
        employee_id=employee_id,
        device_time=when_utc,
        device_now_at_send=device_now,
        method="fingerprint",
        match_score=match_score,
        liveness_passed=liveness,
        photo_base64=None,
        latitude=None,
        longitude=None,
        raw_payload={},
    )
    _process_punch(
        db, device, None, payload, None,
        datetime.now(timezone.utc),
        None, None, None,
    )


def _seed_country_calendar(db, years: list[int]) -> int:
    existing = {
        (r.country_code, r.holiday_date)
        for r in db.scalars(
            select(CountryCalendar).where(CountryCalendar.country_code == "ZA")
        ).all()
    }
    added = 0
    for y in years:
        for (mm, dd), name in _FIXED_ZA_HOLIDAYS:
            hd = date(y, mm, dd)
            if ("ZA", hd) in existing:
                continue
            db.add(CountryCalendar(
                country_code="ZA",
                holiday_date=hd,
                name=name,
                source_ref="seed:fixed-date",
            ))
            added += 1
    db.flush()
    return added


def _seed_org(db) -> tuple[Company, list[Site], list[Department]]:
    company = db.scalar(select(Company))
    if company is None:
        raise RuntimeError("provision_tenant did not create a Company row")
    company.default_timezone = SITE_TZ
    company.trading_name = "Demo Co"
    db.flush()

    branches = [
        Branch(name="Head Office", code="BR-HO", is_active=True, row_version=1),
        Branch(name="Coastal", code="BR-CO", is_active=True, row_version=1),
        Branch(name="Inland", code="BR-IN", is_active=True, row_version=1),
    ]
    for b in branches:
        db.add(b)
    db.flush()

    sites = [
        Site(branch_id=branches[0].id, name="HQ Office", code="SITE-HQ",
             site_type="office", timezone=SITE_TZ, is_active=True, row_version=1),
        Site(branch_id=branches[1].id, name="Durban Depot", code="SITE-DBN",
             site_type="site", timezone=SITE_TZ, is_active=True, row_version=1),
        Site(branch_id=branches[2].id, name="Joburg Store", code="SITE-JHB",
             site_type="store", timezone=SITE_TZ, is_active=True, row_version=1),
    ]
    for s in sites:
        db.add(s)
    db.flush()

    departments = [
        Department(name="Operations", code="DEP-OPS", is_active=True, row_version=1),
        Department(name="Finance", code="DEP-FIN", is_active=True, row_version=1),
        Department(name="HR", code="DEP-HR", is_active=True, row_version=1),
        Department(name="IT", code="DEP-IT", is_active=True, row_version=1),
        Department(name="Field", code="DEP-FLD", is_active=True, row_version=1),
    ]
    for d in departments:
        db.add(d)
    db.flush()

    return company, sites, departments


def _seed_shift(db) -> Shift:
    shift = Shift(
        name="Standard Day",
        start_time=time(8, 0),
        length_minutes=480,
        unpaid_break_minutes=60,
        paid_break_minutes=0,
        grace_late_minutes=10,
        grace_early_minutes=5,
        rounding_minutes=0,
        rounding_mode="nearest",
        min_overtime_minutes=30,
        overtime_requires_approval=True,
        max_shift_minutes=600,
        match_tolerance_minutes=60,
        salaried_premium_mode="full",
        grace_mode="threshold",
        pay_early_arrival=False,
        is_active=True,
        row_version=1,
    )
    db.add(shift)
    db.flush()
    return shift


def _seed_shift_rate_rules(db, shift: Shift) -> int:
    """Demo shift_rate_rule rows so attendance segments produce amounts.

    Multipliers are DEMO PLACEHOLDERS (round-1 §5: no invented money). For
    real tenants these must come from accountant-confirmed policy.
    """
    eff = date(2024, 1, 1)
    existing = {
        (r.day_type, r.kind, r.tier)
        for r in db.scalars(
            select(ShiftRateRule).where(
                ShiftRateRule.shift_id == shift.id,
                ShiftRateRule.effective_from == eff,
            )
        ).all()
    }
    added = 0
    for spec in _DEMO_RATE_RULES:
        key = (spec["day_type"], spec["kind"], spec["tier"])
        if key in existing:
            continue
        db.add(ShiftRateRule(
            shift_id=shift.id,
            day_type=spec["day_type"],
            kind=spec["kind"],
            tier=spec["tier"],
            tier_up_to_minutes=None,
            method=spec["method"],
            value=Decimal(spec["value"]),
            flat_unit=None,
            effective_from=eff,
            effective_to=None,
        ))
        added += 1
    db.flush()
    return added


def _seed_work_pattern(db, shift: Shift) -> WorkPattern:
    wp = WorkPattern(
        name="Mon-Fri Day",
        cycle_length_days=7,
        anchor_date=date(2025, 1, 6),
        is_active=True,
        row_version=1,
    )
    db.add(wp)
    db.flush()
    for i in range(7):
        expected = i < 5
        db.add(WorkPatternDay(
            work_pattern_id=wp.id,
            day_index=i,
            is_expected=expected,
            expected_shift_id=shift.id if expected else None,
        ))
    db.flush()
    return wp


def _seed_employees(db, sites, deps, wp) -> list[Employee]:
    employees: list[Employee] = []
    for i, (first, last) in enumerate(NAMES):
        code = f"EMP-{i + 1:03d}"
        emp = Employee(
            employee_code=code,
            first_name=first,
            last_name=last,
            hire_date=date(2024, 1, 15),
            status="active",
            employee_type="hourly",
            pay_basis="hourly",
            pay_frequency="monthly",
            site_id=sites[i % len(sites)].id,
            department_id=deps[i % len(deps)].id,
            base_rate=None,
            overtime_eligible=True,
            clocks=True,
            medical_aid_dependants=0,
            uif_exempt=False,
            row_version=1,
        )
        db.add(emp)
        db.flush()
        db.add(EmployeeWorkPattern(
            employee_id=emp.id,
            work_pattern_id=wp.id,
            effective_from=date(2024, 1, 1),
            effective_to=None,
        ))
        employees.append(emp)
    db.flush()
    return employees


def _seed_device(db, site: Site) -> tuple[Device, str]:
    raw = secrets.token_hex(32)
    device = Device(
        site_id=site.id,
        name="Seed Device",
        device_type="tablet",
        api_key_hash=hash_device_key(raw),
        status="active",
        allows_code_only=False,
        require_photo_for_code=False,
        software_version="seed",
        pending_punch_count=0,
        row_version=1,
    )
    db.add(device)
    db.flush()
    return device, raw


def _seed_pay_setup(
    db,
    employees: list[Employee],
    admin_user: User | None,
    hr_user: User | None,
) -> None:
    from app.db.tenant.models.payroll_settings import PayrollSettings
    from app.db.tenant.models.pay import EarningType
    from app.services.payroll_formulas import FORMULA_REGISTRY
    from app.services.payroll_seed import ensure_system_earning_types

    settings = db.scalar(select(PayrollSettings))
    if settings is None:
        settings = PayrollSettings(
            id=uuid.uuid4(),
            age_reference_date="date_of_birth",
            sdl_applies=True,
            net_pay_floor=Decimal("0.00"),
            formula_acks={},
            attendance_earning_map={
                "normal|weekday|any": "hourly_normal",
                "normal|saturday|any": "hourly_saturday",
                "normal|sunday|any": "hourly_sunday",
                "normal|public_holiday|any": "hourly_public_holiday",
                "overtime|weekday|1": "overtime_t1",
                "overtime|weekday|2": "overtime_t2",
                "overtime|weekday|3": "overtime_t3",
                "overtime|saturday|1": "overtime_t1",
                "overtime|saturday|2": "overtime_t2",
                "overtime|sunday|1": "overtime_t1",
                "overtime|public_holiday|1": "overtime_t1",
                "allowance|weekday|any": "shift_allowance",
                "allowance|saturday|any": "shift_allowance",
                "allowance|sunday|any": "shift_allowance",
                "allowance|public_holiday|any": "shift_allowance",
            },
            unpaid_day_behaviour="deduct_daily",
            unpaid_day_formula_code="gen_unpaid_absence",
            public_holiday_unworked_monthly="paid",
            public_holiday_paid=True,
            leave_authoritative_source="adjustment",
            monthly_hourly_derivation_formula_code="hourly_rate_from_monthly",
            leave_earning_for_monthly=False,
            demo_values=True,
            row_version=1,
        )
        db.add(settings)
        db.flush()

    now_iso = datetime.now(timezone.utc).isoformat()
    admin_id = str(getattr(admin_user, "id", "")) if admin_user else ""
    settings.formula_acks = {
        code: {"acknowledged_at": now_iso, "acknowledged_by": admin_id}
        for code in FORMULA_REGISTRY
    }
    db.flush()

    ensure_system_earning_types(db)
    db.flush()

    for i, emp in enumerate(employees):
        if i % 2 == 0:
            emp.pay_basis = "monthly"
            emp.pay_frequency = "monthly"
            emp.contracted_weekly_hours = 40.0
            emp.base_rate = None
        else:
            emp.pay_basis = "hourly"
            emp.pay_frequency = "monthly"
            emp.base_rate = Decimal("85.00")
    db.flush()

    base_type = db.scalar(select(EarningType).where(EarningType.code == "BASE_MONTHLY"))
    if base_type is None:
        base_type = EarningType(
            id=uuid.uuid4(),
            name="Base Monthly Salary",
            code="BASE_MONTHLY",
            calc_method="fixed_amount",
            frequency="regular",
            is_taxable=True,
            counts_for_uif=True,
            counts_for_sdl=True,
            proration_rule="none",
            is_system=False,
            is_active=True,
            row_version=1,
        )
        db.add(base_type)
        db.flush()

    db.commit()

    if admin_user is not None and hr_user is not None and admin_user.id != hr_user.id:
        for i, emp in enumerate(employees):
            if i % 2 != 0:
                continue
            payload = {
                "earning_type_id": str(base_type.id),
                "amount": "25000.00",
                "effective_from": "2024-01-01",
            }
            try:
                req = submit_change_request(
                    db, hr_user,
                    kind="employee_earning_create",
                    employee_id=emp.id,
                    payload=payload,
                )
                db.flush()
                approve_change_request(db, admin_user, req.id)
                db.commit()
            except Exception as exc:
                db.rollback()
                print(
                    f"[seed] earning request skipped for {emp.employee_code}: {exc}",
                    file=sys.stderr,
                )


def _seed_punches_and_engine(
    db, employees: list[Employee], device: Device, start_date: date, end_date: date,
) -> None:
    span = (end_date - start_date).days + 1
    for idx, emp in enumerate(employees):
        d = start_date + timedelta(days=(idx % max(span, 1)))
        if d > end_date:
            d = end_date

        if idx % 4 == 0:
            _punch(db, device, emp.id, _utc(d, 8, 0))
        elif idx % 4 == 1:
            _punch(db, device, emp.id, _utc(d, 8, 0))
            _punch(db, device, emp.id, _utc(d, 19, 0))
        elif idx % 4 == 2:
            _punch(db, device, emp.id, _utc(d, 8, 0))
            _punch(db, device, emp.id, _utc(d, 16, 30))
        else:
            _punch(
                db, device, emp.id, _utc(d, 8, 0),
                device_now=_utc(d, 8, 0) + timedelta(seconds=400),
            )
            _punch(
                db, device, emp.id, _utc(d, 16, 30),
                match_score=40, liveness=False,
            )


def _seed_ensure_days_and_recompute(
    db, employees: list[Employee], start_date: date, end_date: date,
) -> None:
    ids = [e.id for e in employees]
    ensure_days(db, ids, start_date, end_date)
    d = start_date
    while d <= end_date:
        for e in employees:
            recompute_day(db, e.id, d)
        d += timedelta(days=1)
    db.commit()


def _backfill_exceptions(
    db, employees: list[Employee], start_date: date,
) -> None:
    types_missing = [
        "missing_in", "low_confidence", "overtime_unapproved",
        "duplicate", "device_clock_gap", "employee_query",
        "absent_expected", "too_long",
    ]
    idx = 0
    for t in types_missing:
        for _ in range(2):
            emp = employees[idx % len(employees)]
            d = start_date + timedelta(days=idx % 10)
            db.add(ExceptionItem(
                id=uuid.uuid4(),
                employee_id=emp.id,
                work_date=d,
                type=t,
                source_ref={"seed": True},
                suggested_fix={},
                status="open",
            ))
            idx += 1
    db.commit()


def _seed_adjustments(db, employees: list[Employee], admin: User | None, start_date: date) -> None:
    adj_admin_id = getattr(admin, "id", None)
    for i, emp in enumerate(employees[:2]):
        d = start_date + timedelta(days=15 + i)
        try:
            _persist_adjustment(
                db,
                employee_id=emp.id,
                work_date=d,
                outcome="leave",
                time_in=None,
                time_out=None,
                reason_code="approved_site_work",
                note="Seed: pre-approved leave",
                created_by=adj_admin_id,
            )
            db.commit()
            recompute_day(db, emp.id, d)
            db.commit()
        except Exception as exc:
            db.rollback()
            print(f"adjustment seed skipped for {emp.employee_code}: {exc}",
                  file=sys.stderr)


def _seed_pay_periods(db, start_date: date, end_date: date) -> tuple[PayPeriod, PayPeriod]:
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end.replace(day=1)

    prev_cutoff = _utc(prev_end, 23, 59)
    open_cutoff = _utc(end_date, 23, 59)

    locked = PayPeriod(
        id=uuid.uuid4(),
        period_key=prev_start.strftime("%Y-%m"),
        start_date=prev_start,
        end_date=prev_end,
        pay_date=prev_end + timedelta(days=5),
        status="locked",
        cutoff_at=prev_cutoff,
    )
    open_ = PayPeriod(
        id=uuid.uuid4(),
        period_key=start_date.strftime("%Y-%m"),
        start_date=start_date,
        end_date=end_date,
        pay_date=end_date + timedelta(days=5),
        status="open",
        cutoff_at=open_cutoff,
    )
    db.add_all([locked, open_])
    db.commit()
    return locked, open_


def _lock_prev_month_days(db, locked: PayPeriod) -> None:
    db.execute(
        text(
            "UPDATE attendance_day SET locked = TRUE "
            "WHERE work_date BETWEEN :s AND :e"
        ),
        {"s": locked.start_date, "e": locked.end_date},
    )
    db.commit()


def _seed_change_requests(db, admin_user: User, employees: list[Employee]) -> None:
    for emp in employees[:3]:
        submit_change_request(
            db, admin_user,
            kind="employee_field_update",
            employee_id=emp.id,
            payload={"row_version": 1, "uif_exempt": True},
            note="Seed: pending change",
        )
        db.commit()


def _refuse_production() -> None:
    env = get_settings().environment
    if env in ("staging", "production"):
        print(f"refusing: environment={env!r}; seed is dev/test only",
              file=sys.stderr)
        sys.exit(1)


def _reset_or_keep(reset: bool) -> None:
    exists = _slug_exists()
    if reset:
        if exists:
            print(f"[seed] --reset: dropping {SLUG}")
            _drop_tenant_and_subscriber()
    else:
        if exists:
            print(f"[seed] --keep: {SLUG} already exists, skipping")
            sys.exit(0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed tenant-demo (B-2 + 4H B-4)")
    parser.add_argument("--reset", action="store_true",
                        help="Drop and recreate the demo tenant")
    parser.add_argument("--keep", action="store_true",
                        help="(default) skip if tenant-demo exists")
    args = parser.parse_args(argv)

    _refuse_production()
    _reset_or_keep(reset=args.reset)

    admin_pw = DEV_PASSWORD_PREFIX + "admin"
    result = provision_tenant(
        slug=SLUG,
        name="Demo Co",
        admin_username="admin",
        admin_password_hash=hash_password(admin_pw),
    )
    print(f"[seed] provisioned {result.slug} → {result.tenant_db_name}")

    db_name = _tenant_db_name(SLUG)
    device_key: str = ""

    today_local = datetime.now(timezone.utc).astimezone(_tz()).date()
    seed_year = today_local.year
    years = [seed_year - 1, seed_year, seed_year + 1]

    with tenant_session(db_name) as db:
        added = _seed_country_calendar(db, years)
        db.commit()
        print(f"[seed] country_calendar: {added} ZA rows across {years[0]}..{years[-1]}")

        company, sites, deps = _seed_org(db)
        shift = _seed_shift(db)
        rules_added = _seed_shift_rate_rules(db, shift)
        db.commit()
        print(f"[seed] shift_rate_rules: {rules_added} DEMO placeholder rows")
        wp = _seed_work_pattern(db, shift)
        employees = _seed_employees(db, sites, deps, wp)
        print(f"[seed] {len(employees)} employees created")

        db.expire_all()
        admin = db.scalar(select(User).where(User.username == "admin"))
        if admin is not None:
            admin.must_change_password = False
            admin.employee_id = employees[0].id
            db.flush()

        for username, role in ROLES_EXTRA:
            existing = db.scalar(select(User).where(User.username == username))
            if existing is None:
                db.add(User(
                    username=username,
                    password_hash=hash_password(DEV_PASSWORD_PREFIX + role),
                    employee_id=None,
                    role=role,
                    is_active=True,
                    must_change_password=False,
                    failed_attempts=0,
                    row_version=1,
                ))
        db.commit()
        print(f"[seed] users: admin/{DEV_PASSWORD_PREFIX}admin + "
              + ", ".join(f"{u}/{DEV_PASSWORD_PREFIX}{r}" for u, r in ROLES_EXTRA))

        admin_ref = db.scalar(select(User).where(User.username == "admin"))
        hr_ref = db.scalar(select(User).where(User.username == "hr"))
        _seed_pay_setup(db, employees, admin_ref, hr_ref)
        print(f"[seed] demo pay setup: demo_values=True, 13 system types, "
              f"base salary for monthly staff, base rate for hourly staff")

        device, device_key = _seed_device(db, sites[0])
        db.commit()

        start_date = today_local.replace(day=1)
        end_date = today_local - timedelta(days=1)
        if end_date < start_date:
            end_date = start_date
        _seed_punches_and_engine(db, employees, device, start_date, end_date)
        print(f"[seed] punches seeded across {start_date}..{end_date}")

        _seed_ensure_days_and_recompute(db, employees, start_date, end_date)
        print(f"[seed] days recomputed")

        _backfill_exceptions(db, employees, start_date)
        print(f"[seed] exceptions backfilled")

        _seed_adjustments(db, employees, admin, start_date)
        print(f"[seed] adjustments seeded")

        locked, open_ = _seed_pay_periods(db, start_date, end_date)
        _lock_prev_month_days(db, locked)
        print(f"[seed] pay periods: {locked.period_key} (locked), "
              f"{open_.period_key} (open)")

        admin_ref2 = db.scalar(select(User).where(User.username == "admin"))
        if admin_ref2 is not None:
            _seed_change_requests(db, admin_ref2, employees)
            print(f"[seed] 3 pending change requests submitted")

    print()
    print("=" * 60)
    print("DEVICE API KEY (shown ONCE — copy it now):")
    print(f"  {device_key}")
    print("=" * 60)
    print()
    print(f"[seed] DONE. Login dev passwords (username → password):")
    print(f"  admin    → {DEV_PASSWORD_PREFIX}admin   (role: payroll_admin)")
    for u, r in ROLES_EXTRA:
        print(f"  {u:<8} → {DEV_PASSWORD_PREFIX}{r}")
    print(f"[seed] See docs/SEED.md for details.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
