'''Device endpoint tests (Chapter 2A).'''
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.v1.device_auth import hash_device_key, require_device
from app.core.errors import AppError
from app.core.security import hash_password
from app.core.usernames import normalise_username
from app.db.tenant.models.attendance import Punch
from app.db.tenant.models.devices import Device
from app.db.tenant.models.organisation import Branch, Site
from app.db.tenant.models.people import Employee, User
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
    from app.services.provisioning import (_drop_tenant_database, _tenant_db_name, provision_tenant,)
    slug = f'dev-{uuid.uuid4().hex[:10]}'
    result = provision_tenant(slug=slug, name='Dev Test Co', admin_username='admin', admin_password_hash=hash_password('TestPassword123!'))
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


def _mk_user(session, *, username, role, password):
    u = User(username=normalise_username(username), password_hash=hash_password(password), role=role, is_active=True, must_change_password=False, employee_id=None, row_version=1)
    session.add(u)
    session.commit()
    return u


def _mk_branch_site(session):
    b = Branch(name='B1', code=f'B-{uuid.uuid4().hex[:6]}', is_active=True, row_version=1)
    session.add(b)
    session.commit()
    s = Site(branch_id=b.id, name='S1', code=f'S-{uuid.uuid4().hex[:6]}', site_type='site', timezone='Africa/Johannesburg', is_active=True, row_version=1)
    session.add(s)
    session.commit()
    return s


def _mk_employee(session, code):
    e = Employee(employee_code=code, first_name='A', last_name='B', hire_date=date(2024, 1, 1), status='active', employee_type='hourly', pay_basis='hourly', pay_frequency='monthly', row_version=1)
    session.add(e)
    session.commit()
    return e


def _fake_request(api_key):
    return Request({'type': 'http', 'method': 'GET', 'path': '/x', 'headers': [(b'x-device-key', api_key.encode())], 'client': ('127.0.0.1', 1)})


def test_list_requires_auth(api):
    client, tenant = api
    r = client.get('/api/v1/devices', headers={'X-Tenant-Slug': tenant.slug})
    assert r.status_code == 401, r.text


def test_list_admin_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    site = _mk_branch_site(db)
    client.post('/api/v1/devices', headers=_auth(tok, tenant.slug), json={'site_id': str(site.id), 'name': 'D1', 'device_type': 'usb_fingerprint'})
    r = client.get('/api/v1/devices', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    assert len(r.json()['items']) == 1


def test_list_hr_forbidden(api, db):
    client, tenant = api
    _mk_user(db, username='hr-dev', role='hr', password='HrDevPass12345!')
    tok = _login(client, tenant.slug, 'hr-dev', 'HrDevPass12345!')
    r = client.get('/api/v1/devices', headers=_auth(tok, tenant.slug))
    assert r.status_code == 403, r.text


def test_create_returns_key_once(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    site = _mk_branch_site(db)
    r = client.post('/api/v1/devices', headers=_auth(tok, tenant.slug), json={'site_id': str(site.id), 'name': 'D1', 'device_type': 'usb_fingerprint'})
    assert r.status_code == 201, r.text
    body = r.json()
    assert 'api_key' in body
    assert len(body['api_key']) == 64
    device_id = body['id']
    r2 = client.get(f'/api/v1/devices/{device_id}', headers=_auth(tok, tenant.slug))
    assert r2.status_code == 200, r2.text
    assert 'api_key' not in r2.json()
    assert 'api_key_hash' not in r2.json()


def test_create_invalid_site(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    r = client.post('/api/v1/devices', headers=_auth(tok, tenant.slug), json={'site_id': str(uuid.uuid4()), 'name': 'D1', 'device_type': 'usb_fingerprint'})
    assert r.status_code == 400, r.text
    assert r.json()['error']['code'] == 'invalid_site'


def test_create_invalid_device_type(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    site = _mk_branch_site(db)
    r = client.post('/api/v1/devices', headers=_auth(tok, tenant.slug), json={'site_id': str(site.id), 'name': 'D1', 'device_type': 'floppy_drive'})
    assert r.status_code == 400, r.text
    assert r.json()['error']['code'] == 'invalid_device_type'


def test_patch_status(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    site = _mk_branch_site(db)
    created = client.post('/api/v1/devices', headers=_auth(tok, tenant.slug), json={'site_id': str(site.id), 'name': 'D1', 'device_type': 'usb_fingerprint'}).json()
    r = client.patch(f'/api/v1/devices/{created['id']}', headers=_auth(tok, tenant.slug), json={'row_version': 1, 'status': 'suspended'})
    assert r.status_code == 200, r.text
    assert r.json()['status'] == 'suspended'
    assert r.json()['row_version'] == 2


def test_delete_unreferenced_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    site = _mk_branch_site(db)
    created = client.post('/api/v1/devices', headers=_auth(tok, tenant.slug), json={'site_id': str(site.id), 'name': 'Deletable', 'device_type': 'usb_fingerprint'}).json()
    did = created['id']
    r = client.delete(f'/api/v1/devices/{did}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 204, r.text
    from sqlalchemy import select as _sel
    db.expire_all()
    assert db.scalar(_sel(Device).where(Device.id == uuid.UUID(did))) is None


def test_delete_with_punches_409(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    site = _mk_branch_site(db)
    created = client.post('/api/v1/devices', headers=_auth(tok, tenant.slug), json={'site_id': str(site.id), 'name': 'HasPunches', 'device_type': 'usb_fingerprint'}).json()
    did = uuid.UUID(created['id'])
    emp = _mk_employee(db, 'P-1')
    now = datetime.now(timezone.utc)
    p = Punch(client_punch_id=uuid.uuid4(), payload_hash='0'*64, employee_id=emp.id, device_id=did, site_id=site.id, device_time=now, effective_time=now, offset_ms=0, method='fingerprint', status='accepted', flags=[], raw_payload={})
    db.add(p)
    db.commit()
    r = client.delete(f'/api/v1/devices/{did}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 409, r.text
    assert r.json()['error']['code'] == 'device_in_use'


def test_device_auth_valid(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    site = _mk_branch_site(db)
    created = client.post('/api/v1/devices', headers=_auth(tok, tenant.slug), json={'site_id': str(site.id), 'name': 'AuthOK', 'device_type': 'usb_fingerprint'}).json()
    raw = created['api_key']
    d = require_device(_fake_request(raw), db, x_device_key=raw)
    assert str(d.id) == created['id']
    assert d.last_seen_at is not None


def test_device_auth_unknown_key(db):
    try:
        require_device(_fake_request('nonexistent'), db, x_device_key='nonexistent')
        assert False, 'unknown key should fail'
    except AppError as e:
        assert e.code == 'device_auth_failed'


def test_device_auth_missing_header(db):
    req = Request({'type': 'http', 'method': 'GET', 'path': '/x', 'headers': [], 'client': ('127.0.0.1', 1)})
    try:
        require_device(req, db, x_device_key=None)
        assert False, 'missing header should fail'
    except AppError as e:
        assert e.code == 'device_auth_failed'


def test_device_auth_inactive(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    site = _mk_branch_site(db)
    created = client.post('/api/v1/devices', headers=_auth(tok, tenant.slug), json={'site_id': str(site.id), 'name': 'Inactive', 'device_type': 'usb_fingerprint'}).json()
    did = created['id']
    raw = created['api_key']
    r = client.patch(f'/api/v1/devices/{did}', headers=_auth(tok, tenant.slug), json={'row_version': 1, 'status': 'inactive'})
    assert r.status_code == 200, r.text
    db.expire_all()
    try:
        require_device(_fake_request(raw), db, x_device_key=raw)
        assert False, 'inactive device should fail'
    except AppError as e:
        assert e.code == 'device_inactive'


def test_rotate_key_invalidates_old_key(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    site = _mk_branch_site(db)
    created = client.post('/api/v1/devices', headers=_auth(tok, tenant.slug), json={'site_id': str(site.id), 'name': 'Rotate', 'device_type': 'usb_fingerprint'}).json()
    did = created['id']
    old_key = created['api_key']
    r = client.post(f'/api/v1/devices/{did}/rotate-key', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    new_key = r.json()['api_key']
    assert new_key != old_key
    db.expire_all()
    try:
        require_device(_fake_request(old_key), db, x_device_key=old_key)
        assert False, 'old key should fail after rotation'
    except AppError as e:
        assert e.code == 'device_auth_failed'
    ok = require_device(_fake_request(new_key), db, x_device_key=new_key)
    assert str(ok.id) == did

# END OF FILE
