"""Punch endpoint tests (Chapter 2A).

Covers the HTTP surface of POST /punches and POST /punches/batch that the
list-scope tests in test_punch_scope.py do not: device authentication, A3
idempotency, A4 status/flags, A5 employee and code-only policy, A6 raw_payload
and photo validation, and per-item batch results.

Photo happy-path is deliberately not tested here: a valid photo would write
to StorageDep and leave files behind. The service-level photo validation is
tested in test_punch_service.py; the wire-level failure paths are tested here.
"""
from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.api.v1.device_auth import hash_device_key
from app.core.security import hash_password
from app.db.tenant.models.devices import Device
from app.db.tenant.models.organisation import Branch, Site
from app.db.tenant.models.people import Employee
from app.db.tenant.session import get_tenant_engine


@dataclass
class _DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def disposable_tenant() -> Iterator[_DisposableTenant]:
    from app.db.control.models import Subscriber
    from app.db.control.session import control_session
    from app.services.provisioning import _drop_tenant_database, _tenant_db_name, provision_tenant
    slug = f'punch-{uuid.uuid4().hex[:10]}'
    result = provision_tenant(slug=slug, name='Punch Test Co', admin_username='admin', admin_password_hash=hash_password('TestPassword123!'))
    db_name = _tenant_db_name(slug)
    try:
        yield _DisposableTenant(slug=result.slug, tenant_db_name=result.tenant_db_name, subscriber_id=result.subscriber_id)
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


def _mk_branch_site(session):
    b = Branch(name=f'B-{uuid.uuid4().hex[:6]}', code=f'B-{uuid.uuid4().hex[:6]}', is_active=True, row_version=1)
    session.add(b)
    session.commit()
    s = Site(branch_id=b.id, name='S', code=f'S-{uuid.uuid4().hex[:6]}', site_type='site', timezone='Africa/Johannesburg', is_active=True, row_version=1)
    session.add(s)
    session.commit()
    return s


def _mk_device(session, site_id, *, allows_code_only=False, require_photo_for_code=True, status='active'):
    raw = secrets.token_hex(32)
    d = Device(
        site_id=site_id,
        name=f'Dev-{uuid.uuid4().hex[:6]}',
        device_type='usb_fingerprint',
        api_key_hash=hash_device_key(raw),
        status=status,
        allows_code_only=allows_code_only,
        require_photo_for_code=require_photo_for_code,
        pending_punch_count=0,
        row_version=1,
    )
    session.add(d)
    session.commit()
    return d, raw


def _mk_employee(session, code, *, status='active', site_id=None):
    e = Employee(
        employee_code=code,
        first_name='A',
        last_name=code,
        hire_date=date(2024, 1, 1),
        status=status,
        site_id=site_id,
        employee_type='hourly',
        pay_basis='hourly',
        pay_frequency='monthly',
        row_version=1,
    )
    session.add(e)
    session.commit()
    return e


def _payload(employee_id, **overrides):
    now = datetime.now(timezone.utc)
    p = {
        'client_punch_id': str(uuid.uuid4()),
        'employee_id': str(employee_id),
        'device_time': now.isoformat(),
        'method': 'fingerprint',
        'match_score': '95',
        'liveness_passed': True,
        'raw_payload': {},
    }
    p.update(overrides)
    return p


def _post(client, slug, device_key, body):
    return client.post(
        '/api/v1/punches',
        headers={'X-Tenant-Slug': slug, 'X-Device-Key': device_key},
        json=body,
    )


# ---------------------------------------------------------------------------
# Authentication (DeviceAuthDep)
# ---------------------------------------------------------------------------


def test_submit_no_device_key_403(api, db):
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, _raw = _mk_device(db, site.id)
    emp = _mk_employee(db, 'NO-AUTH', site_id=site.id)
    r = client.post(
        '/api/v1/punches',
        headers={'X-Tenant-Slug': tenant.slug},
        json=_payload(emp.id),
    )
    assert r.status_code == 403, r.text
    assert r.json()['error']['code'] == 'device_auth_failed'


def test_submit_bad_device_key_403(api, db):
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, _raw = _mk_device(db, site.id)
    emp = _mk_employee(db, 'BAD-AUTH', site_id=site.id)
    r = _post(client, tenant.slug, 'not-a-real-key', _payload(emp.id))
    assert r.status_code == 403, r.text
    assert r.json()['error']['code'] == 'device_auth_failed'


# ---------------------------------------------------------------------------
# Happy path and idempotency (A3)
# ---------------------------------------------------------------------------


def test_submit_ok_201(api, db):
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, raw = _mk_device(db, site.id)
    emp = _mk_employee(db, 'OK-1', site_id=site.id)
    r = _post(client, tenant.slug, raw, _payload(emp.id))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['employee_id'] == str(emp.id)
    assert body['status'] == 'accepted'
    assert body['flags'] == []
    assert body['method'] == 'fingerprint'


def test_submit_idempotent_retry_returns_existing(api, db):
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, raw = _mk_device(db, site.id)
    emp = _mk_employee(db, 'IDEM-1', site_id=site.id)
    payload = _payload(emp.id)
    r1 = _post(client, tenant.slug, raw, payload)
    assert r1.status_code == 201, r1.text
    r2 = _post(client, tenant.slug, raw, payload)
    assert r2.status_code == 201, r2.text
    assert r2.json()['id'] == r1.json()['id']
    assert r2.json()['client_punch_id'] == r1.json()['client_punch_id']


def test_submit_same_uuid_different_payload_409(api, db):
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, raw = _mk_device(db, site.id)
    emp = _mk_employee(db, 'UUID-1', site_id=site.id)
    other = _mk_employee(db, 'UUID-2', site_id=site.id)
    cpid = str(uuid.uuid4())
    p1 = _payload(emp.id, client_punch_id=cpid)
    p2 = _payload(other.id, client_punch_id=cpid)
    r1 = _post(client, tenant.slug, raw, p1)
    assert r1.status_code == 201, r1.text
    r2 = _post(client, tenant.slug, raw, p2)
    assert r2.status_code == 409, r2.text
    assert r2.json()['error']['code'] == 'punch_uuid_reused'


# ---------------------------------------------------------------------------
# A5: employee existence and status
# ---------------------------------------------------------------------------


def test_submit_unknown_employee_422(api, db):
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, raw = _mk_device(db, site.id)
    r = _post(client, tenant.slug, raw, _payload(uuid.uuid4()))
    assert r.status_code == 422, r.text
    assert r.json()['error']['code'] == 'unknown_employee'


def test_submit_terminated_employee_flagged(api, db):
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, raw = _mk_device(db, site.id)
    emp = _mk_employee(db, 'TERM-1', status='terminated', site_id=site.id)
    r = _post(client, tenant.slug, raw, _payload(emp.id))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['status'] == 'rejected'
    assert 'employee_not_active' in body['flags']


# ---------------------------------------------------------------------------
# A2/A4: future-dated punch
# ---------------------------------------------------------------------------


def test_submit_future_time_flagged(api, db):
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, raw = _mk_device(db, site.id)
    emp = _mk_employee(db, 'FUT-1', site_id=site.id)
    now = datetime.now(timezone.utc)
    payload = _payload(
        emp.id,
        device_time=(now + timedelta(hours=1)).isoformat(),
        device_now_at_send=now.isoformat(),
    )
    r = _post(client, tenant.slug, raw, payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['status'] == 'rejected'
    assert 'future_time' in body['flags']


# ---------------------------------------------------------------------------
# A5: code-only policy
# ---------------------------------------------------------------------------


def test_submit_code_only_not_allowed_403(api, db):
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, raw = _mk_device(db, site.id, allows_code_only=False)
    emp = _mk_employee(db, 'CODE-1', site_id=site.id)
    payload = _payload(emp.id, method='code', match_score=None, liveness_passed=None)
    r = _post(client, tenant.slug, raw, payload)
    assert r.status_code == 403, r.text
    assert r.json()['error']['code'] == 'code_not_allowed_here'


def test_submit_code_only_no_photo_400(api, db):
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, raw = _mk_device(db, site.id, allows_code_only=True, require_photo_for_code=True)
    emp = _mk_employee(db, 'CODE-2', site_id=site.id)
    payload = _payload(emp.id, method='code', match_score=None, liveness_passed=None)
    r = _post(client, tenant.slug, raw, payload)
    assert r.status_code == 400, r.text
    assert r.json()['error']['code'] == 'photo_required'


# ---------------------------------------------------------------------------
# A6: raw_payload and photo validation
# ---------------------------------------------------------------------------


def test_submit_raw_payload_template_422(api, db):
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, raw = _mk_device(db, site.id)
    emp = _mk_employee(db, 'TPL-1', site_id=site.id)
    payload = _payload(emp.id, raw_payload={'nested': {'face_template': 'abc'}})
    r = _post(client, tenant.slug, raw, payload)
    assert r.status_code == 422, r.text
    assert r.json()['error']['code'] == 'biometric_template_not_allowed'


def test_submit_raw_payload_oversize_422(api, db):
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, raw = _mk_device(db, site.id)
    emp = _mk_employee(db, 'BIG-1', site_id=site.id)
    payload = _payload(emp.id, raw_payload={'blob': 'x' * 9000})
    r = _post(client, tenant.slug, raw, payload)
    assert r.status_code == 422, r.text
    assert r.json()['error']['code'] == 'raw_payload_too_large'


def test_submit_invalid_photo_base64_400(api, db):
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, raw = _mk_device(db, site.id)
    emp = _mk_employee(db, 'PHOTO-1', site_id=site.id)
    payload = _payload(emp.id, photo_base64='not-valid-base64!!!')
    r = _post(client, tenant.slug, raw, payload)
    assert r.status_code == 400, r.text
    assert r.json()['error']['code'] == 'photo_invalid'


# ---------------------------------------------------------------------------
# Batch endpoint
# ---------------------------------------------------------------------------


def test_submit_batch_mixed_200(api, db):
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, raw = _mk_device(db, site.id)
    emp_ok = _mk_employee(db, 'BATCH-OK', site_id=site.id)
    body = {'punches': [_payload(emp_ok.id), _payload(uuid.uuid4())]}
    r = client.post(
        '/api/v1/punches/batch',
        headers={'X-Tenant-Slug': tenant.slug, 'X-Device-Key': raw},
        json=body,
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out['accepted'] == 1
    assert out['rejected'] == 1
    assert out['results'][0]['ok'] is True
    assert out['results'][0]['punch']['employee_id'] == str(emp_ok.id)
    assert out['results'][1]['ok'] is False
    assert out['results'][1]['error']['code'] == 'unknown_employee'

# END OF FILE