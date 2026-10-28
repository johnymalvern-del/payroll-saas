'''Work pattern endpoint tests (Chapter 2A).'''
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.usernames import normalise_username
from app.db.tenant.models.attendance import WorkPattern, WorkPatternDay
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
    from app.services.provisioning import (
        _drop_tenant_database, _tenant_db_name, provision_tenant,
    )
    slug = f'wp-{uuid.uuid4().hex[:10]}'
    result = provision_tenant(slug=slug, name='Work Pattern Test Co', admin_username='admin', admin_password_hash=hash_password('TestPassword123!'))
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


def _mk_pattern(session, *, name='Default', cycle_length_days=7, anchor_date=None, days=None):
    p = WorkPattern(name=name, cycle_length_days=cycle_length_days, anchor_date=anchor_date or date(2024, 1, 1), is_active=True, row_version=1)
    session.add(p)
    session.commit()
    if days is None:
        days = [{'day_index': i, 'is_expected': i < 5} for i in range(cycle_length_days)]
    for d in days:
        session.add(WorkPatternDay(work_pattern_id=p.id, day_index=d['day_index'], is_expected=d['is_expected'], expected_shift_id=d.get('expected_shift_id')))
    session.commit()
    return p


def test_list_requires_auth(api):
    client, tenant = api
    r = client.get('/api/v1/work-patterns', headers={'X-Tenant-Slug': tenant.slug})
    assert r.status_code == 401, r.text


def test_list_payroll_admin_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_pattern(db, name='Weekly')
    r = client.get('/api/v1/work-patterns', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    assert len(r.json()['items']) == 1


def test_list_hr_forbidden(api, db):
    client, tenant = api
    _mk_user(db, username='hr-wp', role='hr', password='HrWpPass12345!')
    tok = _login(client, tenant.slug, 'hr-wp', 'HrWpPass12345!')
    r = client.get('/api/v1/work-patterns', headers=_auth(tok, tenant.slug))
    assert r.status_code == 403, r.text


def test_create_weekly_ok(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    payload = {'name': 'Weekly 5on2off', 'cycle_length_days': 7, 'anchor_date': '2024-01-01', 'days': [{'day_index': i, 'is_expected': i < 5} for i in range(7)]}
    r = client.post('/api/v1/work-patterns', headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['cycle_length_days'] == 7
    assert len(body['days']) == 7
    assert body['row_version'] == 1


def test_create_4on4off_ok(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    days = [{'day_index': i, 'is_expected': i < 4} for i in range(8)]
    payload = {'name': '4on4off', 'cycle_length_days': 8, 'anchor_date': '2024-01-01', 'days': days}
    r = client.post('/api/v1/work-patterns', headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 201, r.text
    assert r.json()['cycle_length_days'] == 8
    assert len(r.json()['days']) == 8


def test_create_duplicate_name(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    payload = {'name': 'Dupe', 'cycle_length_days': 7, 'anchor_date': '2024-01-01', 'days': [{'day_index': i, 'is_expected': True} for i in range(7)]}
    client.post('/api/v1/work-patterns', headers=_auth(tok, tenant.slug), json=payload)
    r = client.post('/api/v1/work-patterns', headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 409, r.text
    assert r.json()['error']['code'] == 'duplicate_name'


def test_create_days_incomplete(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    payload = {'name': 'Incomplete', 'cycle_length_days': 7, 'anchor_date': '2024-01-01', 'days': [{'day_index': i, 'is_expected': True} for i in range(5)]}
    r = client.post('/api/v1/work-patterns', headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 422, r.text


def test_get_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    p = _mk_pattern(db, name='GetMe')
    r = client.get(f'/api/v1/work-patterns/{p.id}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['name'] == 'GetMe'
    assert len(body['days']) == 7


def test_get_not_found(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    r = client.get(f'/api/v1/work-patterns/{uuid.uuid4()}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 404, r.text


def test_patch_days_replaces(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    p = _mk_pattern(db, name='PatchMe')
    new_days = [{'day_index': i, 'is_expected': i >= 4} for i in range(7)]
    r = client.patch(f'/api/v1/work-patterns/{p.id}', headers=_auth(tok, tenant.slug), json={'row_version': 1, 'days': new_days})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['row_version'] == 2
    assert len(body['days']) == 7
    expected = sorted(d['is_expected'] for d in new_days)
    actual = sorted(d['is_expected'] for d in body['days'])
    assert expected == actual


def test_patch_stale_version(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    p = _mk_pattern(db, name='Stale')
    r = client.patch(f'/api/v1/work-patterns/{p.id}', headers=_auth(tok, tenant.slug), json={'row_version': 99, 'name': 'X'})
    assert r.status_code == 409, r.text
    assert r.json()['error']['code'] == 'record_changed'


def test_delete_unreferenced_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    p = _mk_pattern(db, name='Deletable')
    p_id = p.id
    r = client.delete(f'/api/v1/work-patterns/{p_id}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 204, r.text
    db.expire_all()
    assert db.scalar(select(WorkPattern).where(WorkPattern.id == p_id)) is None


def test_list_include_inactive(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_pattern(db, name='Active')
    p2 = _mk_pattern(db, name='Inactive')
    p2.is_active = False
    db.commit()
    r1 = client.get('/api/v1/work-patterns', headers=_auth(tok, tenant.slug))
    assert r1.status_code == 200, r1.text
    names = {p['name'] for p in r1.json()['items']}
    assert 'Active' in names and 'Inactive' not in names
    r2 = client.get('/api/v1/work-patterns?include_inactive=true', headers=_auth(tok, tenant.slug))
    names2 = {p['name'] for p in r2.json()['items']}
    assert 'Active' in names2 and 'Inactive' in names2

# END OF FILE
