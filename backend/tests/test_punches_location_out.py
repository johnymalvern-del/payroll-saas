"""Nested PunchOut.location read path (privacy policy s5).

Proves the transitional shape introduced before ten_0031: the fix is exposed
as a nested object so clients can migrate off the flat fields before those
columns are dropped.

Deliberately a separate module from test_punches_geofence.py. That file
proves the verdict is computed correctly; this one proves the fix survives
the round trip and disappears cleanly when retention deletes it. Different
concern, and the fixture duplication is a handful of helpers rather than a
shared harness.

test_purged_location_reads_as_null_and_verdict_survives is the one that
matters: it is the whole point of section 5 -- the personal data goes, the
audit conclusion stays.
"""
from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.api.v1.device_auth import hash_device_key
from app.core.security import hash_password
from app.db.tenant.models.attendance import Punch, PunchLocation
from app.db.tenant.models.devices import Device
from app.db.tenant.models.organisation import Branch, Site
from app.db.tenant.models.people import Employee
from app.db.tenant.session import get_tenant_engine
from app.services.attendance_retention import purge_expired_coordinates

CT_LAT = Decimal("-33.924900")
CT_LON = Decimal("18.424100")
INSIDE_LAT = Decimal("-33.924400")


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

    slug = f"loc-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Location Out Test Co",
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
def api(api_client, disposable_tenant):
    return api_client, disposable_tenant


@pytest.fixture()
def db(disposable_tenant):
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()


def _mk_site(session, *, radius=100):
    branch = Branch(
        name=f"B-{uuid.uuid4().hex[:6]}",
        code=f"B-{uuid.uuid4().hex[:6]}",
        is_active=True,
        row_version=1,
    )
    session.add(branch)
    session.commit()
    site = Site(
        branch_id=branch.id,
        name="S",
        code=f"S-{uuid.uuid4().hex[:6]}",
        site_type="site",
        timezone="Africa/Johannesburg",
        is_active=True,
        row_version=1,
        latitude=CT_LAT,
        longitude=CT_LON,
        geofence_radius_m=radius,
    )
    session.add(site)
    session.commit()
    return site


def _mk_device(session, site_id):
    raw = secrets.token_hex(32)
    device = Device(
        site_id=site_id,
        name=f"Dev-{uuid.uuid4().hex[:6]}",
        device_type="usb_fingerprint",
        api_key_hash=hash_device_key(raw),
        status="active",
        allows_code_only=False,
        require_photo_for_code=True,
        pending_punch_count=0,
        row_version=1,
    )
    session.add(device)
    session.commit()
    return device, raw


def _mk_employee(session, site_id):
    employee = Employee(
        employee_code=f"E-{uuid.uuid4().hex[:6]}",
        first_name="A",
        last_name="L",
        hire_date=date(2024, 1, 1),
        status="active",
        site_id=site_id,
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        row_version=1,
    )
    session.add(employee)
    session.commit()
    return employee


def _payload(employee_id, **overrides):
    now = datetime.now(timezone.utc)
    body = {
        "client_punch_id": str(uuid.uuid4()),
        "employee_id": str(employee_id),
        "device_time": now.isoformat(),
        "method": "fingerprint",
        "match_score": "95",
        "liveness_passed": True,
        "raw_payload": {},
    }
    body.update(overrides)
    return body


def _post(client, slug, device_key, body):
    return client.post(
        "/api/v1/punches",
        headers={"X-Tenant-Slug": slug, "X-Device-Key": device_key},
        json=body,
    )


def _setup(api, db):
    client, tenant = api
    site = _mk_site(db)
    _device, raw = _mk_device(db, site.id)
    employee = _mk_employee(db, site.id)
    return client, tenant, raw, employee


def test_create_response_includes_nested_location(api, db):
    client, tenant, raw, employee = _setup(api, db)
    r = _post(
        client, tenant.slug, raw,
        _payload(employee.id, latitude=str(INSIDE_LAT), longitude=str(CT_LON),
                 gps_accuracy_m="7.5"),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "location" in body, body
    loc = body["location"]
    assert loc is not None, "create response must carry the fix"
    assert float(loc["latitude"]) == pytest.approx(float(INSIDE_LAT), abs=1e-6)
    assert float(loc["longitude"]) == pytest.approx(float(CT_LON), abs=1e-6)
    assert float(loc["gps_accuracy_m"]) == pytest.approx(7.5)
    assert loc["distance_m"] is not None
    assert loc["captured_at"] is not None


def test_create_response_location_is_null_without_a_fix(api, db):
    client, tenant, raw, employee = _setup(api, db)
    r = _post(client, tenant.slug, raw, _payload(employee.id))
    assert r.status_code == 201, r.text
    body = r.json()
    assert "location" in body, body
    assert body["location"] is None


def test_purged_location_reads_as_null_and_verdict_survives(api, db):
    """The point of section 5: personal data goes, audit conclusion stays.

    The punch is submitted with an effective_time 45 days in the past by
    sending device_now_at_send alongside device_time -- that is how an
    offline device reports a queued punch, and it is what makes the row
    eligible for retention immediately rather than waiting 30 days.
    """
    client, tenant, raw, employee = _setup(api, db)
    old = datetime.now(timezone.utc) - timedelta(days=45)
    r = _post(
        client, tenant.slug, raw,
        _payload(
            employee.id,
            device_time=old.isoformat(),
            device_now_at_send=datetime.now(timezone.utc).isoformat(),
            latitude=str(INSIDE_LAT),
            longitude=str(CT_LON),
            gps_accuracy_m="5",
        ),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["location"] is not None
    punch_id = uuid.UUID(body["id"])

    db.expire_all()
    result = purge_expired_coordinates(db, dry_run=False)
    db.commit()
    assert result.purged == 1, result.as_dict()

    db.expire_all()
    row = db.get(Punch, punch_id)
    assert row is not None
    assert row.location is None, "the fix must be gone"
    # The audit conclusion is untouched.
    assert row.geofence_result == "inside"
    assert row.geofence_reason == "within_geofence"
    assert row.distance_band == "within"
    assert row.status == "accepted"

# END OF FILE