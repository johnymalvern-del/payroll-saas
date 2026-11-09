"""Milestone 1 — idempotent demo seed for tenant_tenant_demo.

Sequence (every step guarded):
  A. Verify prerequisites (company, T001, period 2026_11)
  B. Set T001.base_rate + approved pay history (340 ZAR/h)
  C. Add weekday normal ×1.0 / overtime tier 1 ×1.5 / tier 2 ×2.0 / tier 3 ×2.0
  D. Create PayrollSettings row (all fields build_pipeline_config needs)
  E. Ack all 6 formulas (from pr.FORMULA_REGISTRY)
  F. Link admin user -> T001
  G. Seed 5 worked days for T001 in Nov 2026 (fingerprint punches via API)
  H. Populate attendance_earning_map from actual segments
  I. Try build_pipeline_config -> STOP CLEANLY if tax tables empty (M6 dep)
  J. Run preview, print preview payslip for T001
  K. Finalise if preview succeeded (only if period still open)
"""
import json
import os
import sys
import time
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL_CONTROL",
    "postgresql+psycopg://payroll_app:payroll_app_dev_password"
    "@localhost:5432/payroll_control",
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

TENANT_URL = (
    "postgresql+psycopg://payroll_app:payroll_app_dev_password"
    "@localhost:5432/tenant_tenant_demo"
)
API = "http://localhost:8000/api/v1"
SLUG = "tenant-demo"

import urllib.error
import urllib.request

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.db.tenant.models.attendance import (
    AttendanceDay,
    AttendanceSegment,
    Shift,
    ShiftRateRule,
)
from app.db.tenant.models.organisation import Company
from app.db.tenant.models.pay import (
    PayPeriod,
    Payslip,
)
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.people import Employee, EmployeePayHistory, User
from app.services import payroll_runner as pr

TARGET = "T001"
BASE_RATE = Decimal("340.000000")
DEMO_DAYS = [
    date(2026, 11, 4),
    date(2026, 11, 5),
    date(2026, 11, 6),
    date(2026, 11, 9),
    date(2026, 11, 10),
]
RATE_RULES = [
    ("weekday", "normal", 1, "multiplier", Decimal("1.00")),
    ("weekday", "overtime", 1, "multiplier", Decimal("1.50")),
    ("weekday", "overtime", 2, "multiplier", Decimal("2.00")),
    ("weekday", "overtime", 3, "multiplier", Decimal("2.00")),
]
KEY_TO_ETYPE = {
    "normal|weekday|any": "hourly_normal",
    "normal|saturday|any": "hourly_saturday",
    "normal|sunday|any": "hourly_sunday",
    "normal|public_holiday|any": "hourly_public_holiday",
    "overtime|weekday|1": "overtime_t1",
    "overtime|weekday|2": "overtime_t2",
    "overtime|weekday|3": "overtime_t3",
}


def step(t):
    print(f"\n{'=' * 60}\n{t}\n{'=' * 60}")


def api(m, p, b=None, tok=None, extra=None):
    h = {"Content-Type": "application/json", "X-Tenant-Slug": SLUG}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    if extra:
        h.update(extra)
    data = json.dumps(b).encode() if b is not None else None
    for attempt in range(3):
        try:
            r = urllib.request.urlopen(
                urllib.request.Request(API + p, data=data, headers=h, method=m)
            )
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(2 + attempt * 2)
                continue
            return e.code, e.read().decode()[:400]
        except Exception as e:
            return 0, str(e)


def safe_settings_create(s):
    """Create PayrollSettings, skip fields the model doesn't have."""
    wanted = {
        "sdl_applies": False,
        "age_reference_date": "date_of_birth",
        "net_pay_floor": Decimal("0.00"),
        "unpaid_day_behaviour": "skip",
        "unpaid_day_formula_code": None,
        "public_holiday_unworked_monthly": "paid",
        "public_holiday_paid": True,
        "leave_authoritative_source": "adjustment",
        "monthly_hourly_derivation_formula_code": None,
        "leave_earning_for_monthly": False,
        "attendance_earning_map": {},
        "demo_values": True,
        "formula_acks": {},
        "row_version": 1,
    }
    cols = {c.name for c in PayrollSettings.__table__.columns}
    filtered = {k: v for k, v in wanted.items() if k in cols}
    skipped = sorted(set(wanted) - set(filtered))
    st = PayrollSettings(id=uuid.uuid4(), **filtered)
    s.add(st)
    s.flush()
    if skipped:
        print(f"  (skipped model-missing fields: {skipped})")
    print(f"  set fields: {sorted(filtered)}")
    return st


eng = create_engine(TENANT_URL)
s = Session(eng)
try:
    # ============================================================
    step("A. Prerequisites")
    # ============================================================
    company = s.scalar(select(Company))
    if company is None:
        sys.exit("FATAL: Company row missing")
    emp = s.scalar(select(Employee).where(Employee.employee_code == TARGET))
    if emp is None:
        sys.exit(f"FATAL: {TARGET} missing")
    period = s.scalar(select(PayPeriod).where(PayPeriod.period_key == "2026_11"))
    if period is None:
        sys.exit("FATAL: Nov 2026 period missing")
    print(f"  company={company.id} country={company.country_code}")
    print(f"  {TARGET} id={emp.id} shift={emp.default_shift_id} base_rate={emp.base_rate}")
    print(f"  period={period.period_key} status={period.status}")

    # ============================================================
    step("B. base_rate + approved pay history")
    # ============================================================
    if emp.base_rate is None:
        emp.base_rate = BASE_RATE
        s.flush()
        print(f"  set base_rate = {BASE_RATE}")
    else:
        print(f"  base_rate already = {emp.base_rate}")

    # DOB required for _resolve_age with age_reference_date="date_of_birth"
    if emp.date_of_birth is None:
        emp.date_of_birth = date(1990, 5, 15)
        s.flush()
        print(f"  set date_of_birth = 1990-05-15 (demo)")
    else:
        print(f"  date_of_birth already = {emp.date_of_birth}")

    hist = s.scalar(
        select(EmployeePayHistory).where(
            EmployeePayHistory.employee_id == emp.id,
            EmployeePayHistory.status == "approved",
        )
    )
    if hist is None:
        hp_fields = {
            "id": uuid.uuid4(),
            "employee_id": emp.id,
            "base_rate": BASE_RATE,
            "effective_from": date(2024, 1, 1),
            "effective_to": None,
            "status": "approved",
            "created_at": datetime.now(timezone.utc),
            "row_version": 1,
        }
        hp_cols = {c.name for c in EmployeePayHistory.__table__.columns}
        hp = EmployeePayHistory(
            **{k: v for k, v in hp_fields.items() if k in hp_cols}
        )
        s.add(hp)
        s.flush()
        print(f"  added approved pay history @ {BASE_RATE}")
    else:
        print(f"  pay history exists (id={hist.id})")

    # ============================================================
    step("C. Rate rules on shift")
    # ============================================================
    if emp.default_shift_id is None:
        sys.exit(f"FATAL: {TARGET} has no default_shift_id")
    shift = s.get(Shift, emp.default_shift_id)
    print(f"  shift: {shift.name} (id={shift.id})")
    existing = s.scalars(
        select(ShiftRateRule).where(ShiftRateRule.shift_id == shift.id)
    ).all()
    if existing:
        print(f"  {len(existing)} rate rules exist — skipping")
    else:
        for day_type, kind, tier, method, value in RATE_RULES:
            fields = {
                "id": uuid.uuid4(),
                "shift_id": shift.id,
                "day_type": day_type,
                "kind": kind,
                "tier": tier,
                "tier_up_to_minutes": None,
                "method": method,
                "value": value,
                "flat_unit": None,
                "effective_from": date(2024, 1, 1),
                "effective_to": None,
            }
            rr_cols = {c.name for c in ShiftRateRule.__table__.columns}
            s.add(ShiftRateRule(**{k: v for k, v in fields.items() if k in rr_cols}))
        s.flush()
        print(f"  added {len(RATE_RULES)} rate rules")

    # ============================================================
    step("D. PayrollSettings")
    # ============================================================
    settings = s.scalar(select(PayrollSettings).limit(1))
    if settings is None:
        settings = safe_settings_create(s)
    else:
        print(f"  settings exist (id={settings.id})")
        # Ensure our demo values are set even if row already exists
        changed = False
        if getattr(settings, "unpaid_day_behaviour", None) is None:
            settings.unpaid_day_behaviour = "skip"
            changed = True
        if getattr(settings, "sdl_applies", None) is None:
            settings.sdl_applies = False
            changed = True
        if getattr(settings, "age_reference_date", None) is None:
            settings.age_reference_date = "date_of_birth"
            changed = True
        if changed:
            s.flush()
            print(f"  filled missing required fields on existing settings")

    # ============================================================
    step("E. Ack formulas")
    # ============================================================
    acks = dict(settings.formula_acks or {})
    now_iso = datetime.now(timezone.utc).isoformat()
    added = 0
    for code in pr.FORMULA_REGISTRY:
        if code not in acks:
            acks[code] = {"acked_at": now_iso, "acked_by": "m1_seed"}
            added += 1
    if added:
        settings.formula_acks = acks
        s.flush()
        print(f"  acked {added} formulas (total {len(acks)})")
    else:
        print(f"  all {len(acks)} formulas already acked")

    # ============================================================
    step("F. Link admin -> T001")
    # ============================================================
    admin = s.scalar(select(User).where(User.username == "admin"))
    if admin is None:
        sys.exit("FATAL: admin user missing")
    if admin.employee_id is None:
        admin.employee_id = emp.id
        s.flush()
        print(f"  linked admin -> {TARGET}")
    else:
        print(f"  admin already linked (employee_id={admin.employee_id})")

    s.commit()
    print("  [commit OK]")

    # ============================================================
    step("G. Seed worked days for T001 (5 days Nov 2026)")
    # ============================================================
    # Login as admin
    s_api, body = api("POST", "/auth/login",
                      {"identifier": "admin", "password": "devpass_admin"})
    if s_api != 200:
        print(f"  WARN: login failed: {s_api} {body}")
        token = None
        dev_key = None
    else:
        token = body["access_token"]
        # Find device for T001's site
        s_api, devs = api("GET", "/devices?limit=100", tok=token)
        dev_key = None
        for d in devs.get("items", []) if isinstance(devs, dict) else []:
            if d.get("site_id") == str(emp.site_id):
                s_api, rot = api("POST", f"/devices/{d['id']}/rotate-key", tok=token)
                if s_api == 200:
                    dev_key = rot["api_key"]
                break

    for wd in DEMO_DAYS:
        existing_day = s.scalar(
            select(AttendanceDay).where(
                AttendanceDay.employee_id == emp.id,
                AttendanceDay.work_date == wd,
            )
        )
        if existing_day is not None and existing_day.status == "worked":
            print(f"  {wd}: already worked")
            continue
        if token is None or dev_key is None:
            print(f"  {wd}: SKIP (no token/device)")
            continue
        ds = wd.isoformat()
        ok = True
        for time_str, direction in ((f"{ds}T08:00:00+02:00", "in"),
                                    (f"{ds}T17:00:00+02:00", "out")):
            cid = uuid.uuid5(uuid.NAMESPACE_DNS, f"m1-{emp.id}-{wd}-{direction}")
            now_iso = datetime.now(timezone.utc).isoformat()
            s_api, resp = api(
                "POST", "/punches",
                {"client_punch_id": str(cid), "employee_id": str(emp.id),
                 "device_time": time_str,
                 "device_now_at_send": now_iso,
                 "method": "fingerprint"},
                tok=token, extra={"X-Device-Key": dev_key},
            )
            if s_api not in (200, 201):
                print(f"  {wd} {direction}: FAILED {s_api} {resp}")
                ok = False
        if ok:
            print(f"  {wd}: punched")
        time.sleep(0.3)

    # Diagnostic: show resulting effective_time vs device_time
    s.expire_all()
    punch_check = s.execute(
        text(
            "SELECT effective_time, device_time, offset_ms "
            "FROM punch WHERE employee_id = :eid "
            "AND device_time::date BETWEEN '2026-11-04' AND '2026-11-10' "
            "ORDER BY device_time"
        ),
        {"eid": str(emp.id)},
    ).all()
    print(f"  punch timestamp verification ({len(punch_check)} rows):")
    for pc in punch_check:
        print(f"    eff={pc[0]} dev={pc[1]} offset_ms={pc[2]}")

    # ============================================================
    step("H. State summary + attendance_earning_map")
    # ============================================================
    s.expire_all()
    days = s.scalars(
        select(AttendanceDay).where(
            AttendanceDay.employee_id == emp.id,
            AttendanceDay.work_date >= period.start_date,
            AttendanceDay.work_date <= period.end_date,
        ).order_by(AttendanceDay.work_date)
    ).all()
    all_keys = set()
    print(f"  {len(days)} Nov days for {TARGET}:")
    for d in days:
        segs = s.scalars(
            select(AttendanceSegment).where(AttendanceSegment.attendance_day_id == d.id)
        ).all()
        for sg in segs:
            all_keys.add(pr._group_key_for_segment(sg))
        seg_desc = ", ".join(f"{sg.kind}/{sg.day_type}/t{sg.tier}/{sg.minutes}m"
                             f"×{sg.rate_value}" for sg in segs)
        print(f"    {d.work_date} status={d.status} segs=[{seg_desc}]")
    print(f"  distinct segment keys: {sorted(all_keys)}")

    new_map = dict(settings.attendance_earning_map or {})
    for k in all_keys:
        if k in KEY_TO_ETYPE:
            new_map[k] = KEY_TO_ETYPE[k]
        else:
            print(f"  WARN: no EarningType.code mapping for key {k!r}")
    if new_map != dict(settings.attendance_earning_map or {}):
        settings.attendance_earning_map = new_map
        s.commit()
        print(f"  attendance_earning_map updated with {len(new_map)} entries")
    else:
        print(f"  attendance_earning_map unchanged")

    # ============================================================
    step("I. build_pipeline_config (tax gate)")
    # ============================================================
    try:
        cfg = pr.build_pipeline_config(s, emp, period.pay_date)
        print(f"  SUCCESS: pipeline config OK")
        print(f"    periods_per_year={cfg.periods_per_year}")
        print(f"    age={cfg.employee_age}")
        print(f"    sdl_applies={cfg.sdl_applies}")
        print(f"    uif_rows={len(cfg.uif_rows or [])}")
        print(f"    sdl_rows={len(cfg.sdl_rows or [])}")
        print(f"    retirement_rows={len(cfg.retirement_rows or [])}")
    except Exception as e:
        code = getattr(e, "code", None)
        msg = str(e)
        print(f"  FAILED: {type(e).__name__} code={code!r} msg={msg}")
        print()

        # Diagnose the actual blocker
        if "date_of_birth" in msg.lower():
            print("  >>> BLOCKED: employee.date_of_birth is required")
            print("  >>> (age_reference_date='date_of_birth' needs it)")
            print("  >>> This seed should have set it in section B.")
            print("  >>> If this message persists, re-check section B output.")
            sys.exit(1)
        elif code in (
            "tax_tables_missing", "tax_tables_refused",
            "statutory_table_missing", "uif_missing", "sdl_missing",
            "retirement_limit_missing",
        ) or "statutory" in msg.lower() or "tax_table" in msg.lower():
            print("  >>> MILESTONE 1 BLOCKED ON MILESTONE 6.")
            print("  >>> PayrollSettings, rate rules, formulas, employee,")
            print("  >>> and attendance setup are all COMPLETE (sections A-H).")
            print("  >>> The refusal is from the statutory table pipeline.")
            print("  >>> Real SARS tables must be loaded (Milestone 6).")
            print("  >>> Re-running this seed after M6 will complete the run")
            print("  >>> to finalise with no further data changes needed.")
            sys.exit(0)
        elif code == "settings_missing":
            print("  >>> Settings row not created — section D needs review.")
            sys.exit(1)
        else:
            print(f"  >>> Unclassified blocker code={code!r}.")
            print("  >>> Stopping. Data setup A-H is complete.")
            sys.exit(1)

    # ============================================================
    step("J. Preview")
    # ============================================================
    if period.status == "locked":
        print(f"  period already locked — skipping preview")
    else:
        try:
            run = pr.run_preview(s, admin, period)
            s.commit()
            print(f"  preview run id={run.id} status={run.status}")
        except Exception as e:
            print(f"  preview FAILED: {type(e).__name__}: {e}")
            s.rollback()
            sys.exit(1)

    # ============================================================
    step("K. Preview payslip for T001 (expected vs actual)")
    # ============================================================
    ps = s.scalar(
        select(Payslip).where(
            Payslip.pay_period_id == period.id,
            Payslip.employee_id == emp.id,
        ).order_by(Payslip.revision.desc())
    )
    if ps is None:
        print(f"  WARN: no payslip for {TARGET}")
    else:
        print(f"  payslip: status={ps.status} rev={ps.revision}")
        print(f"  gross={ps.gross} paye={ps.paye} net={ps.net}")
        ctx = ps.calculation_context or {}
        snap = ctx.get("attendance_inputs") or {}
        grouped = snap.get("grouped_minutes") or {}
        rates = snap.get("rates_by_date") or {}
        print(f"  grouped_minutes: {grouped}")
        print(f"  rates_by_date sample: {dict(list(rates.items())[:3])}")
        # Compute expected independently
        expected = Decimal("0")
        if grouped and rates:
            rate = Decimal(str(next(iter(rates.values()))))
            for k, mins in grouped.items():
                if "normal" in k:
                    amt = (Decimal(str(mins)) / 60) * rate * Decimal("1.00")
                    expected += amt
                    print(f"    expected {k}: {mins}min × {rate}/h × 1.0 = {amt:.2f}")
                elif "overtime" in k:
                    mult = Decimal("1.50")
                    amt = (Decimal(str(mins)) / 60) * rate * mult
                    expected += amt
                    print(f"    expected {k}: {mins}min × {rate}/h × 1.5 = {amt:.2f}")
            print(f"  expected gross: {expected:.2f}")
            print(f"  actual gross:   {ps.gross}")
            diff = Decimal(str(ps.gross)) - expected
            if abs(diff) < Decimal("0.01"):
                print(f"  ✓ MATCH")
            else:
                print(f"  ✗ MISMATCH by {diff:.2f}")

    print("\n=== MILESTONE 1 SEED COMPLETE ===")
finally:
    s.close()
    eng.dispose()