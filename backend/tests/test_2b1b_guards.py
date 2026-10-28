"""Guards extended for 2B: site_in_use counts punches and devices,
shift_in_use counts attendance_days (per amendment B12)."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy.orm import Session

from app.api.v1.device_auth import hash_device_key
from app.core.security import hash_password
from app.db.tenant.models.attendance import AttendanceDay, Punch, Shift
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
    slug = f'guards-{uuid.uuid4().hex[:10]}'
    result = provision_tenant(slug=slug, name='Guards Test', admin_username='admin', admin_password_hash=hash_password('TestPassword123!'))
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


def _login(client, slug, username, password):
    r = client.post('/api/v1/auth/login', headers={'X-Tenant-Slug': slug}, json={'identifier': username, 'password': password})
    assert r.status_code == 200, r.text
    return r.json()['access_token']


def _auth(token, slug):
    return {'Authorization': f'Bearer {token}', 'X-Tenant-Slug': slug}


def _admin_token(client, slug):
    token = _login(client, slug, 'admin', 'TestPassword123!')
    r = client.post('/api/v1/auth/change-password', headers={**_auth(token, slug), 'Content-Type': 'application/json'}, json={'current_password': 'TestPassword123!', 'new_password': 'PostChange123!'})
    assert r.status_code in (200, 204), r.text
    return _login(client, slug, 'admin', 'PostChange123!')


def _mk_bs(session):
    b = Branch(name='B', code=f'B-{uuid.uuid4().hex[:6]}', is_active=True, row_version=1)
    session.add(b); session.commit()
    s = Site(branch_id=b.id, name='S', code=f'S-{uuid.uuid4().hex[:6]}', site_type='site', timezone='Africa/Johannesburg', is_active=True, row_version=1)
    session.add(s); session.commit()
    return b, s


def _mk_emp(session, code, site_id=None):
    e = Employee(employee_code=code, first_name='A', last_name=code, hire_date=date(2024, 1, 1), status='active', site_id=site_id, employee_type='hourly', pay_basis='hourly', pay_frequency='monthly', row_version=1)
    session.add(e); session.commit()
    return e


def _mk_shift(session):
    s = Shift(name=f'S-{uuid.uuid4().hex[:6]}', start_time=time(8, 0), length_minutes=480, unpaid_break_minutes=60, paid_break_minutes=0, grace_late_minutes=0, grace_early_minutes=0, rounding_minutes=0, rounding_mode='nearest', min_overtime_minutes=0, overtime_requires_approval=True, max_shift_minutes=720, match_tolerance_minutes=60, salaried_premium_mode='full', is_active=True, row_version=1)
    session.add(s); session.commit()
    return s


def test_site_delete_unreferenced_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _b, s = _mk_bs(db)
    r = client.delete(f'/api/v1/sites/{s.id}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 204, r.text


def test_site_delete_blocked_by_punches(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _b, s = _mk_bs(db)
    emp = _mk_emp(db, 'P-1', site_id=s.id)
    now = datetime.now(timezone.utc)
    p = Punch(client_punch_id=uuid.uuid4(), payload_hash='0'*64, employee_id=emp.id, device_id=None, site_id=s.id, device_time=now, effective_time=now, offset_ms=0, method='fingerprint', status='accepted', flags=[], raw_payload={})
    db.add(p); db.commit()
    r = client.delete(f'/api/v1/sites/{s.id}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 409, r.text
    body = r.json()
    assert body['error']['code'] == 'site_in_use'
    assert body['error']['details']['punches'] == 1


def test_site_delete_blocked_by_devices(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _b, s = _mk_bs(db)
    d = Device(site_id=s.id, name='D', device_type='usb_fingerprint', api_key_hash=hash_device_key('a'*64), status='active', allows_code_only=False, require_photo_for_code=True, pending_punch_count=0, row_version=1)
    db.add(d); db.commit()
    r = client.delete(f'/api/v1/sites/{s.id}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 409, r.text
    assert r.json()['error']['code'] == 'site_in_use'


def test_shift_delete_blocked_by_attendance_days(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    shift = _mk_shift(db)
    emp = _mk_emp(db, 'A-1')
    ad = AttendanceDay(employee_id=emp.id, work_date=date(2024, 5, 1), status='worked', shift_id=shift.id, worked_minutes=480, normal_minutes=480, overtime_minutes=0, raw_minutes=480, flags=[], source_version=0, locked=False, row_version=1)
    db.add(ad); db.commit()
    r = client.delete(f'/api/v1/shifts/{shift.id}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 409, r.text
    body = r.json()
    assert body['error']['code'] == 'shift_in_use'
    assert body['error']['details']['attendance_days'] == 1

# END OF FILE
