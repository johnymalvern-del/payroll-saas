"""Fraud heuristics wired into punch ingest.

test_fraud.py pins the arithmetic with no database. This file proves the
wiring: that a punch flagged impossible_travel is still status='accepted',
still creates a punch row, and also raises an HR-visible exception.

Two things about the setup that are easy to get wrong and were, once:

  device_now_at_send is the device's clock AT THE MOMENT OF SENDING, not the
  time of the punch. effective_time is corrected to server time using the
  difference between them, so setting both to the same past timestamp pulls
  every punch forward to approximately "now" and collapses the interval to
  milliseconds. That made the travel checks return INCONCLUSIVE and made two
  tests pass vacuously.

  A CountryCalendar row must exist for the punch's year. recompute_day raises
  holiday_calendar_missing without one, and _process_punch swallows that into
  warnings=["attendance_recompute_failed"] -- so the punch is written, the flag
  is written, and no exception is ever created. The warning assertion in
  test_impossible_travel_raises_an_hr_exception exists so a swallowed recompute
  failure cannot hide behind a passing flag test again.

Punch times are in the past because is_future_time would otherwise reject them.
"""
from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.v1.device_auth import hash_device_key
from app.core.security import hash_password
from app.db.tenant.models.attendance import (
    CountryCalendar,
    ExceptionItem,
    Punch,
    PunchLocation,
)
from app.db.tenant.models.devices import Device
from app.db.tenant.models.organisation import Branch, Site
from app.db.tenant.models.people import Employee
from app.db.tenant.session import get_tenant_engine

CT_LAT = Decimal("-33.924900")
CT_LON = Decimal("18.424100")
# ~19 km away: no road connects them in two minutes.
FAR_LAT = Decimal("-33.902900")
FAR_LON = Decimal("18.629800")


@dataclass
class _DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def disposable_tenant() -> Iterator[_DisposableTenant]:
    from app.db.control.models import Subscriber
    from app.db.control.session import control_session
    from app.services.provisioning import (
        _drop_tenant_database,
        _tenant_db_name,
        provision_tenant,
    )

    slug = f"fraud-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Fraud Test Co",
        admin_username="admin",
        admin_password_hash=hash_password("TestPassword123!"),
    )
    db_name = _tenant_db_name(slug)
    try:
        yield _DisposableTenant(
            slug=result.slug,
            tenant_db_name=result.tenant_db_name,
            subscriber_id=result.subscriber_id,
        )
    finally:
        try:
            _drop_tenant_database(db_name)
        except Exception:
            pass
        with control_session() as session:
            row = session.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if row is not None:
                session.delete(row)


@pytest.fixture()
def db(disposable_tenant):
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()


def _seed_calendar(session, *years):
    """One holiday per year is enough: the engine only requires the year to
    exist, and a missing year is an error rather than an empty holiday list.

    Two years are seeded because recompute_day also rebuilds the previous local
    day, which crosses into the prior year on 1 January.
    """
    for year in years:
        session.add(
            CountryCalendar(
                country_code="ZA",
                holiday_date=date(year, 1, 1),
                name="New Year",
                source_ref="test",
            )
        )
    session.commit()


@pytest.fixture()
def setup(api_client, db, disposable_tenant):
    this_year = datetime.now(timezone.utc).year
    _seed_calendar(db, this_year, this_year - 1)

    branch = Branch(
        name=f"B-{uuid.uuid4().hex[:6]}",
        code=f"B-{uuid.uuid4().hex[:6]}",
        is_active=True,
        row_version=1,
    )
    db.add(branch)
    db.commit()
    site = Site(
        branch_id=branch.id,
        name="S",
        code=f"S-{uuid.uuid4().hex[:6]}",
        site_type="site",
        timezone="Africa/Johannesburg",
        is_active=True,
        row_version=1,
    )
    db.add(site)
    db.commit()

    raw = secrets.token_hex(32)
    db.add(
        Device(
            site_id=site.id,
            name=f"Dev-{uuid.uuid4().hex[:6]}",
            device_type="usb_fingerprint",
            api_key_hash=hash_device_key(raw),
            status="active",
            allows_code_only=True,
            require_photo_for_code=False,
            pending_punch_count=0,
            row_version=1,
        )
    )
    db.commit()

    employee = Employee(
        employee_code=f"E-{uuid.uuid4().hex[:6]}",
        first_name="A",
        last_name="L",
        hire_date=date(2024, 1, 1),
        status="active",
        site_id=site.id,
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        row_version=1,
    )
    db.add(employee)
    db.commit()

    return api_client, disposable_tenant, raw, employee


def _payload(employee_id, when, **overrides):
    """A punch body. `when` is the punch time; the device is 'sending' now.

    Keeping the two distinct is what makes the interval between punches real
    rather than sub-second. See the module docstring.
    """
    body = {
        "client_punch_id": str(uuid.uuid4()),
        "employee_id": str(employee_id),
        "device_time": when.isoformat(),
        "device_now_at_send": datetime.now(timezone.utc).isoformat(),
        "method": "code",
        "raw_payload": {},
    }
    body.update(overrides)
    return body


def _post(client, slug, key, body):
    return client.post(
        "/api/v1/punches",
        headers={"X-Tenant-Slug": slug, "X-Device-Key": key},
        json=body,
    )


def _ago(**kwargs):
    return datetime.now(timezone.utc) - timedelta(**kwargs)


def _open_types(db, employee_id):
    return set(
        db.scalars(
            select(ExceptionItem.type).where(
                ExceptionItem.employee_id == employee_id,
                ExceptionItem.status == "open",
            )
        ).all()
    )


# ---------------------------------------------------------------------------
# Impossible travel
# ---------------------------------------------------------------------------


def test_impossible_travel_flags_but_never_rejects(setup, db):
    """The safeguard. A suspicion must not remove a punch from pay."""
    client, tenant, key, employee = setup

    first = _post(
        client, tenant.slug, key,
        _payload(employee.id, _ago(minutes=10),
                 latitude=str(CT_LAT), longitude=str(CT_LON),
                 gps_accuracy_m="5"),
    )
    assert first.status_code == 201, first.text

    second = _post(
        client, tenant.slug, key,
        _payload(employee.id, _ago(minutes=8),
                 latitude=str(FAR_LAT), longitude=str(FAR_LON),
                 gps_accuracy_m="5"),
    )
    assert second.status_code == 201, second.text
    body = second.json()

    assert "impossible_travel" in body["flags"], f"flags were {body['flags']}"
    assert body["status"] == "accepted", (
        "a fraud flag must never change punch status -- a rejected punch "
        "does not count toward attendance"
    )


def test_impossible_travel_raises_an_hr_exception(setup, db):
    """The flag must reach HR, not just the punch row.

    The warnings assertion is the important part. _process_punch swallows any
    recompute failure into warnings=["attendance_recompute_failed"], so a
    missing holiday calendar -- or any other engine error -- leaves the flag on
    the punch and no exception in the queue. Without this check the test would
    fail with "no exception" and say nothing about why.
    """
    client, tenant, key, employee = setup

    first = _post(client, tenant.slug, key,
                  _payload(employee.id, _ago(minutes=10),
                           latitude=str(CT_LAT), longitude=str(CT_LON),
                           gps_accuracy_m="5"))
    assert first.status_code == 201, first.text
    assert first.json().get("warnings") == [], (
        f"recompute failed on the first punch: {first.json().get('warnings')}"
    )

    second = _post(client, tenant.slug, key,
                   _payload(employee.id, _ago(minutes=8),
                            latitude=str(FAR_LAT), longitude=str(FAR_LON),
                            gps_accuracy_m="5"))
    assert second.status_code == 201, second.text
    assert second.json().get("warnings") == [], (
        f"recompute failed on the second punch: {second.json().get('warnings')}"
    )
    assert "impossible_travel" in second.json()["flags"]

    db.expire_all()
    assert "impossible_travel" in _open_types(db, employee.id), (
        "the flag must reach the exception queue, not just the punch row"
    )


def test_distant_punches_hours_apart_do_not_flag(setup, db):
    """~19 km over two hours is a commute, not impossible travel.

    The gap is asserted rather than assumed: if the fixture ever collapsed the
    interval again, this would go back to passing vacuously.
    """
    client, tenant, key, employee = setup

    _post(client, tenant.slug, key,
          _payload(employee.id, _ago(hours=6),
                   latitude=str(CT_LAT), longitude=str(CT_LON),
                   gps_accuracy_m="5"))
    r = _post(client, tenant.slug, key,
              _payload(employee.id, _ago(hours=4),
                       latitude=str(FAR_LAT), longitude=str(FAR_LON),
                       gps_accuracy_m="5"))

    assert r.status_code == 201, r.text
    assert "impossible_travel" not in r.json()["flags"]

    db.expire_all()
    times = list(db.scalars(
        select(Punch.effective_time)
        .where(Punch.employee_id == employee.id)
        .order_by(Punch.effective_time)
    ).all())
    assert len(times) == 2
    gap_minutes = (times[1] - times[0]).total_seconds() / 60.0
    assert gap_minutes > 60, (
        f"punches were only {gap_minutes:.2f} min apart -- the fixture is not "
        f"producing the scenario this test claims to check"
    )


def test_same_place_minutes_apart_does_not_flag(setup, db):
    client, tenant, key, employee = setup

    _post(client, tenant.slug, key,
          _payload(employee.id, _ago(minutes=10),
                   latitude=str(CT_LAT), longitude=str(CT_LON),
                   gps_accuracy_m="5"))
    r = _post(client, tenant.slug, key,
              _payload(employee.id, _ago(minutes=8),
                       latitude=str(CT_LAT), longitude=str(CT_LON),
                       gps_accuracy_m="5"))

    assert r.status_code == 201, r.text
    assert "impossible_travel" not in r.json()["flags"]

    # Same guard as above: two minutes apart at zero distance is the claim.
    db.expire_all()
    times = list(db.scalars(
        select(Punch.effective_time)
        .where(Punch.employee_id == employee.id)
        .order_by(Punch.effective_time)
    ).all())
    assert len(times) == 2
    gap_seconds = (times[1] - times[0]).total_seconds()
    assert gap_seconds > 60, (
        f"punches were only {gap_seconds:.1f}s apart, below the assessable minimum"
    )


def test_purged_previous_location_does_not_flag(setup, db):
    """Retention deletes the previous fix; the check must not read that as OK.

    Without the location the comparison is UNAVAILABLE, which raises no flag.
    The first punch is identified explicitly: an unfiltered select would count
    the second punch's location, which exists and should exist.
    """
    client, tenant, key, employee = setup

    first = _post(client, tenant.slug, key,
                  _payload(employee.id, _ago(minutes=10),
                           latitude=str(CT_LAT), longitude=str(CT_LON),
                           gps_accuracy_m="5"))
    assert first.status_code == 201, first.text
    first_id = uuid.UUID(first.json()["id"])

    # Simulate the retention sweep having deleted the raw coordinate.
    db.execute(delete(PunchLocation).where(PunchLocation.punch_id == first_id))
    db.commit()

    r = _post(client, tenant.slug, key,
              _payload(employee.id, _ago(minutes=8),
                       latitude=str(FAR_LAT), longitude=str(FAR_LON),
                       gps_accuracy_m="5"))

    assert r.status_code == 201, r.text
    assert "impossible_travel" not in r.json()["flags"], (
        "a purged reference fix is unknown, not clean"
    )

    db.expire_all()
    assert db.scalar(
        select(PunchLocation).where(PunchLocation.punch_id == first_id)
    ) is None, "the older punch's coordinates must be gone"
    assert db.get(Punch, first_id) is not None, "the older punch must survive"


# ---------------------------------------------------------------------------
# Rapid succession
# ---------------------------------------------------------------------------


def test_rapid_succession_flags_a_flood(setup):
    client, tenant, key, employee = setup

    last = None
    for i in range(6):
        last = _post(
            client, tenant.slug, key,
            _payload(employee.id, _ago(minutes=10 - i)),
        )
        assert last.status_code == 201, last.text

    assert last is not None
    assert "rapid_succession" in last.json()["flags"]
    assert last.json()["status"] == "accepted"


def test_a_normal_day_does_not_flag(setup):
    client, tenant, key, employee = setup

    # Four punches: in, break out, break in, out. Spread over nine hours.
    for hours_ago in (9, 5, 4, 0):
        r = _post(client, tenant.slug, key,
                  _payload(employee.id, _ago(hours=hours_ago)))
        assert r.status_code == 201, r.text
        assert "rapid_succession" not in r.json()["flags"]

# END OF FILE