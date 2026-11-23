"""Geofence verdict tests for POST /punches (Phase 2).

test_punches.py proves the geofence block does not crash. This file proves
it produces the *right answer*: given a device at a known site, a known
punch location and a known accuracy, the persisted verdict must be the one
the Phase 1 evaluator specifies.

The fixtures here are deliberately self-contained rather than imported
from test_punches.py. Module-level pytest fixtures are not visible across
test modules, and hoisting these into conftest.py would couple this file
to a file this phase is not meant to touch. The duplication is four small
helpers; the decoupling is worth it.

The most important test in this file is
test_outside_geofence_still_accepted_and_flagged: an out-of-fence punch
must remain status='accepted'. That is the safeguard that stops a GPS
problem from silently becoming an unpaid deduction downstream.
"""
from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.device_auth import hash_device_key
from app.core.security import hash_password
from app.db.tenant.models.attendance import Punch
from app.db.tenant.models.devices import Device
from app.db.tenant.models.organisation import Branch, Site
from app.db.tenant.models.people import Employee
from app.db.tenant.session import get_tenant_engine


# Cape Town CBD. The site is placed here and punches are offset from it.
CT_LAT = Decimal("-33.924900")
CT_LON = Decimal("18.424100")

# ~19.15 km away: comfortably outside any sensible fence.
FAR_LAT = Decimal("-33.902900")
FAR_LON = Decimal("18.629800")

# ~111 m north: pairs with a 100 m radius and 12 m accuracy to straddle.
NEAR_LAT = Decimal("-33.923900")

# ~55.6 m north: unambiguously inside a 100 m fence at 5 m accuracy.
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

    slug = f'geofence-{uuid.uuid4().hex[:10]}'
    result = provision_tenant(
        slug=slug,
        name='Geofence Test Co',
        admin_username='admin',
        admin_password_hash=hash_password('TestPassword123!'),
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


def _mk_site(session, *, lat=None, lon=None, radius=None):
    """Branch + Site, optionally geofenced."""
    branch = Branch(
        name=f'B-{uuid.uuid4().hex[:6]}',
        code=f'B-{uuid.uuid4().hex[:6]}',
        is_active=True,
        row_version=1,
    )
    session.add(branch)
    session.commit()
    site = Site(
        branch_id=branch.id,
        name='S',
        code=f'S-{uuid.uuid4().hex[:6]}',
        site_type='site',
        timezone='Africa/Johannesburg',
        is_active=True,
        row_version=1,
        latitude=lat,
        longitude=lon,
        geofence_radius_m=radius,
    )
    session.add(site)
    session.commit()
    return site


def _mk_device(session, site_id):
    raw = secrets.token_hex(32)
    device = Device(
        site_id=site_id,
        name=f'Dev-{uuid.uuid4().hex[:6]}',
        device_type='usb_fingerprint',
        api_key_hash=hash_device_key(raw),
        status='active',
        allows_code_only=False,
        require_photo_for_code=True,
        pending_punch_count=0,
        row_version=1,
    )
    session.add(device)
    session.commit()
    return device, raw


def _mk_employee(session, code, site_id):
    employee = Employee(
        employee_code=code,
        first_name='A',
        last_name=code,
        hire_date=date(2024, 1, 1),
        status='active',
        site_id=site_id,
        employee_type='hourly',
        pay_basis='hourly',
        pay_frequency='monthly',
        row_version=1,
    )
    session.add(employee)
    session.commit()
    return employee


def _payload(employee_id, **overrides):
    now = datetime.now(timezone.utc)
    body = {
        'client_punch_id': str(uuid.uuid4()),
        'employee_id': str(employee_id),
        'device_time': now.isoformat(),
        'method': 'fingerprint',
        'match_score': '95',
        'liveness_passed': True,
        'raw_payload': {},
    }
    body.update(overrides)
    return body


def _post(client, slug, device_key, body):
    return client.post(
        '/api/v1/punches',
        headers={'X-Tenant-Slug': slug, 'X-Device-Key': device_key},
        json=body,
    )


def _num(value):
    """PunchOut serialises Numeric columns as Decimal->str; accept both."""
    if value is None:
        return None
    return float(value)


def _setup(api, db, *, lat=CT_LAT, lon=CT_LON, radius=100):
    client, tenant = api
    site = _mk_site(db, lat=lat, lon=lon, radius=radius)
    _device, raw = _mk_device(db, site.id)
    employee = _mk_employee(db, f'E-{uuid.uuid4().hex[:6]}', site.id)
    return client, tenant, site, raw, employee


# ---------------------------------------------------------------------------
# The four verdicts
# ---------------------------------------------------------------------------


def test_inside_geofence_accepted(api, db):
    client, tenant, _site, raw, employee = _setup(api, db)
    r = _post(
        client, tenant.slug, raw,
        _payload(employee.id, latitude=str(INSIDE_LAT), longitude=str(CT_LON), gps_accuracy_m='5'),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['geofence_result'] == 'inside'
    assert body['geofence_reason'] == 'within_geofence'
    assert body['status'] == 'accepted'
    assert 'geofence_outside' not in body['flags']
    assert 'geofence_inconclusive' not in body['flags']
    assert 0.0 < _num(body['distance_m']) < 100.0


def test_outside_geofence_still_accepted_and_flagged(api, db):
    """An out-of-fence punch is recorded, never rejected.

    This is the deduction safeguard. If this test ever fails because
    status became 'rejected', a GPS problem has started discarding
    clock-ins.
    """
    client, tenant, _site, raw, employee = _setup(api, db)
    r = _post(
        client, tenant.slug, raw,
        _payload(employee.id, latitude=str(FAR_LAT), longitude=str(FAR_LON), gps_accuracy_m='5'),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['geofence_result'] == 'outside'
    assert body['geofence_reason'] == 'outside_geofence'
    assert body['status'] == 'accepted', 'outside-geofence must not reject the punch'
    assert 'geofence_outside' in body['flags']
    assert _num(body['distance_m']) > 18_000


def test_poor_accuracy_is_inconclusive(api, db):
    # ~111 m out, 100 m radius, 12 m accuracy: the error circle straddles.
    client, tenant, _site, raw, employee = _setup(api, db)
    r = _post(
        client, tenant.slug, raw,
        _payload(employee.id, latitude=str(NEAR_LAT), longitude=str(CT_LON), gps_accuracy_m='12'),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['geofence_result'] == 'inconclusive'
    assert body['geofence_reason'] == 'accuracy_overlaps_boundary'
    assert body['status'] == 'accepted'
    assert 'geofence_inconclusive' in body['flags']


def test_missing_accuracy_is_inconclusive_not_inside(api, db):
    """Zero distance is not a pass when accuracy is unknown."""
    client, tenant, _site, raw, employee = _setup(api, db)
    r = _post(
        client, tenant.slug, raw,
        _payload(employee.id, latitude=str(CT_LAT), longitude=str(CT_LON)),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['geofence_result'] == 'inconclusive'
    assert body['geofence_reason'] == 'gps_accuracy_unknown'
    assert body['gps_accuracy_m'] is None


def test_site_without_radius_is_unavailable(api, db):
    client, tenant, _site, raw, employee = _setup(api, db, radius=None)
    r = _post(
        client, tenant.slug, raw,
        _payload(employee.id, latitude=str(CT_LAT), longitude=str(CT_LON), gps_accuracy_m='5'),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['geofence_result'] == 'unavailable'
    assert body['geofence_reason'] == 'site_radius_not_configured'
    assert body['status'] == 'accepted'


# ---------------------------------------------------------------------------
# Persistence and idempotency
# ---------------------------------------------------------------------------


def test_verdict_and_accuracy_persisted_on_row(api, db):
    client, tenant, _site, raw, employee = _setup(api, db)
    cpid = str(uuid.uuid4())
    r = _post(
        client, tenant.slug, raw,
        _payload(
            employee.id, client_punch_id=cpid,
            latitude=str(INSIDE_LAT), longitude=str(CT_LON), gps_accuracy_m='7.5',
        ),
    )
    assert r.status_code == 201, r.text

    db.rollback()
    row = db.scalar(select(Punch).where(Punch.client_punch_id == uuid.UUID(cpid)))
    assert row is not None
    assert row.geofence_result == 'inside'
    assert row.geofence_reason == 'within_geofence'
    assert float(row.gps_accuracy_m) == pytest.approx(7.5)
    assert float(row.distance_m) > 0.0


def test_idempotent_replay_preserves_verdict_and_writes_one_row(api, db):
    """Same client_punch_id twice must dedupe, not conflict.

    Two things have to hold for the replay to be recognised as the *same*
    punch:

      * device_time must match, because canonical_payload_hash includes
        it -- an offline device retrying a queued punch re-sends its
        original timestamp, so pinning it here mirrors real behaviour.

      * gps_accuracy_m must NOT be hashed. A retry whose accuracy drifted
        by a metre is still the same punch. This test pins that decision:
        if accuracy were added to the hash, the second call would raise
        409 punch_uuid_reused and this assertion would fail.
    """
    client, tenant, _site, raw, employee = _setup(api, db)
    cpid = str(uuid.uuid4())
    common = dict(
        client_punch_id=cpid,
        device_time=datetime.now(timezone.utc).isoformat(),
        latitude=str(INSIDE_LAT),
        longitude=str(CT_LON),
    )

    first = _post(client, tenant.slug, raw, _payload(employee.id, gps_accuracy_m='5', **common))
    assert first.status_code == 201, first.text
    first_body = first.json()

    second = _post(client, tenant.slug, raw, _payload(employee.id, gps_accuracy_m='6', **common))
    assert second.status_code == 201, second.text
    assert second.json()['id'] == first_body['id']
    assert second.json()['geofence_result'] == first_body['geofence_result']

    db.rollback()
    count = db.scalar(
        select(func.count()).select_from(Punch).where(Punch.client_punch_id == uuid.UUID(cpid))
    )
    assert count == 1


def test_different_payload_same_uuid_still_conflicts(api, db):
    """Idempotency must remain strict about the hashed fields."""
    client, tenant, _site, raw, employee = _setup(api, db)
    cpid = str(uuid.uuid4())

    first = _post(
        client, tenant.slug, raw,
        _payload(employee.id, client_punch_id=cpid,
                 latitude=str(CT_LAT), longitude=str(CT_LON), gps_accuracy_m='5'),
    )
    assert first.status_code == 201, first.text

    second = _post(
        client, tenant.slug, raw,
        _payload(employee.id, client_punch_id=cpid,
                 latitude=str(FAR_LAT), longitude=str(FAR_LON), gps_accuracy_m='5'),
    )
    assert second.status_code == 409, second.text
    assert second.json()['error']['code'] == 'punch_uuid_reused'

# END OF FILE