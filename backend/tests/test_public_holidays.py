'''Public holiday tenant override tests (Chapter 2A).'''
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.usernames import normalise_username
from app.db.tenant.models.attendance import PublicHolidayTenant
from app.db.tenant.models.organisation import Branch, Department, Site
from app.db.tenant.models.people import User
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
    slug = f'ph-{uuid.uuid4().hex[:10]}'
    result = provision_tenant(slug=slug, name='PH Test Co', admin_username='admin', admin_password_hash=hash_password('TestPassword123!'))
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


def _mk_ph(session, holiday_date, name='Holiday', site_id=None, department_id=None, is_working_day_override=False):
    h = PublicHolidayTenant(holiday_date=holiday_date, name=name, site_id=site_id, department_id=department_id, is_working_day_override=is_working_day_override, is_active=True, row_version=1)
    session.add(h)
    session.commit()
    return h


def test_list_requires_auth(api):
    client, tenant = api
    r = client.get('/api/v1/public-holidays', headers={'X-Tenant-Slug': tenant.slug})
    assert r.status_code == 401, r.text


def test_list_payroll_admin_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_ph(db, date(2024, 12, 25), name='Christmas')
    r = client.get('/api/v1/public-holidays', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    assert len(r.json()['items']) == 1


def test_list_hr_forbidden(api, db):
    client, tenant = api
    _mk_user(db, username='hr-ph', role='hr', password='HrPhPass12345!')
    tok = _login(client, tenant.slug, 'hr-ph', 'HrPhPass12345!')
    r = client.get('/api/v1/public-holidays', headers=_auth(tok, tenant.slug))
    assert r.status_code == 403, r.text


def test_create_ok(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    r = client.post('/api/v1/public-holidays', headers=_auth(tok, tenant.slug), json={'holiday_date': '2024-12-25', 'name': 'Christmas'})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['name'] == 'Christmas'
    assert body['is_working_day_override'] is False
    assert body['row_version'] == 1


def test_create_with_site_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    b = Branch(name='B1', code='B1-PH', is_active=True, row_version=1)
    db.add(b)
    db.commit()
    s = Site(branch_id=b.id, name='S1', code='S1-PH', site_type='site', timezone='Africa/Johannesburg', is_active=True, row_version=1)
    db.add(s)
    db.commit()
    r = client.post('/api/v1/public-holidays', headers=_auth(tok, tenant.slug), json={'holiday_date': '2024-12-25', 'name': 'Xmas', 'site_id': str(s.id)})
    assert r.status_code == 201, r.text
    assert r.json()['site_id'] == str(s.id)


def test_create_invalid_site_400(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    r = client.post('/api/v1/public-holidays', headers=_auth(tok, tenant.slug), json={'holiday_date': '2024-12-25', 'name': 'Xmas', 'site_id': str(uuid.uuid4())})
    assert r.status_code == 400, r.text
    assert r.json()['error']['code'] == 'invalid_site'


def test_patch_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    h = _mk_ph(db, date(2024, 12, 25), name='Christmas')
    r = client.patch(f'/api/v1/public-holidays/{h.id}', headers=_auth(tok, tenant.slug), json={'row_version': 1, 'name': 'Xmas Day'})
    assert r.status_code == 200, r.text
    assert r.json()['name'] == 'Xmas Day'
    assert r.json()['row_version'] == 2


def test_patch_stale_version(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    h = _mk_ph(db, date(2024, 12, 25))
    r = client.patch(f'/api/v1/public-holidays/{h.id}', headers=_auth(tok, tenant.slug), json={'row_version': 99, 'name': 'X'})
    assert r.status_code == 409, r.text
    assert r.json()['error']['code'] == 'record_changed'


def test_delete_future_ok(api, db):
    from sqlalchemy import select
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    future = date.today() + timedelta(days=30)
    h = _mk_ph(db, future)
    h_id = h.id
    r = client.delete(f'/api/v1/public-holidays/{h_id}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 204, r.text
    db.expire_all()
    assert db.scalar(select(PublicHolidayTenant).where(PublicHolidayTenant.id == h_id)) is None


def test_delete_past_409(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    h = _mk_ph(db, date(2024, 1, 1), name='Past')
    r = client.delete(f'/api/v1/public-holidays/{h.id}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 409, r.text
    assert r.json()['error']['code'] == 'public_holiday_in_use'

# END OF FILE
