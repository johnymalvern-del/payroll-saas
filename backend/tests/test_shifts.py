'''Shift endpoint tests (Chapter 2A).'''
from __future__ import annotations

import uuid
from sqlalchemy import select
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.usernames import normalise_username
from app.db.tenant.models.attendance import Shift, ShiftRateRule
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
        _drop_tenant_database,
        _tenant_db_name,
        provision_tenant,
    )
    slug = f'shifts-{uuid.uuid4().hex[:10]}'
    result = provision_tenant(slug=slug, name='Shifts Test Co', admin_username='admin', admin_password_hash=hash_password('TestPassword123!'))
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
    token = r.json().get('access_token')
    assert token, r.text
    return token


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


def _mk_shift(session, *, name='Default', **kwargs):
    s = Shift(name=name, start_time=time(8, 0), length_minutes=480, unpaid_break_minutes=60, paid_break_minutes=0, grace_late_minutes=10, grace_early_minutes=5, rounding_minutes=5, rounding_mode='nearest', min_overtime_minutes=15, overtime_requires_approval=True, max_shift_minutes=720, match_tolerance_minutes=60, salaried_premium_mode='full', **kwargs)
    session.add(s)
    session.commit()
    return s


def _mk_rate_rule(session, shift_id):
    r = ShiftRateRule(shift_id=shift_id, day_type='weekday', kind='normal', tier=1, tier_up_to_minutes=None, method='multiplier', value=1.0, effective_from=date(2024, 1, 1))
    session.add(r)
    session.commit()
    return r


def test_list_requires_auth(api):
    client, tenant = api
    r = client.get('/api/v1/shifts', headers={'X-Tenant-Slug': tenant.slug})
    assert r.status_code == 401, r.text


def test_list_payroll_admin_ok(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    r = client.get('/api/v1/shifts', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    body = r.json()
    assert 'items' in body and 'next_cursor' in body


def test_list_hr_forbidden(api, db):
    client, tenant = api
    _mk_user(db, username='hr-shifts', role='hr', password='HrShiftsPass123!')
    tok = _login(client, tenant.slug, 'hr-shifts', 'HrShiftsPass123!')
    r = client.get('/api/v1/shifts', headers=_auth(tok, tenant.slug))
    assert r.status_code == 403, r.text


def test_create_ok(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    r = client.post('/api/v1/shifts', headers=_auth(tok, tenant.slug), json={'name': 'Day Shift', 'start_time': '08:00:00', 'length_minutes': 480, 'max_shift_minutes': 720, 'unpaid_break_minutes': 60, 'grace_late_minutes': 5, 'grace_early_minutes': 0, 'rounding_minutes': 5, 'rounding_mode': 'nearest', 'min_overtime_minutes': 15, 'overtime_requires_approval': True, 'match_tolerance_minutes': 60, 'salaried_premium_mode': 'full'})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['name'] == 'Day Shift'
    assert body['length_minutes'] == 480
    assert body['row_version'] == 1
    assert body['is_active'] is True


def test_create_duplicate_name_case_insensitive(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    payload = {'name': 'Day', 'start_time': '08:00:00', 'length_minutes': 480, 'max_shift_minutes': 720}
    client.post('/api/v1/shifts', headers=_auth(tok, tenant.slug), json=payload)
    payload['name'] = 'day'
    r = client.post('/api/v1/shifts', headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 409, r.text
    assert r.json()['error']['code'] == 'duplicate_name'


def test_create_max_shift_too_small(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    r = client.post('/api/v1/shifts', headers=_auth(tok, tenant.slug), json={'name': 'Bad', 'start_time': '08:00:00', 'length_minutes': 480, 'max_shift_minutes': 480})
    assert r.status_code == 400, r.text
    assert r.json()['error']['code'] == 'invalid_max_shift'


def test_create_invalid_rounding_mode(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    r = client.post('/api/v1/shifts', headers=_auth(tok, tenant.slug), json={'name': 'Bad', 'start_time': '08:00:00', 'length_minutes': 480, 'max_shift_minutes': 720, 'rounding_mode': 'invalid'})
    assert r.status_code == 422, r.text


def test_get_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    shift = _mk_shift(db, name='Get Test')
    r = client.get(f'/api/v1/shifts/{shift.id}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    assert r.json()['name'] == 'Get Test'


def test_get_not_found(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    r = client.get(f'/api/v1/shifts/{uuid.uuid4()}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 404, r.text
    assert r.json()['error']['code'] == 'record_not_found'


def test_patch_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    shift = _mk_shift(db, name='Original')
    r = client.patch(f'/api/v1/shifts/{shift.id}', headers=_auth(tok, tenant.slug), json={'row_version': 1, 'name': 'Renamed'})
    assert r.status_code == 200, r.text
    assert r.json()['name'] == 'Renamed'
    assert r.json()['row_version'] == 2


def test_patch_stale_version(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    shift = _mk_shift(db)
    r = client.patch(f'/api/v1/shifts/{shift.id}', headers=_auth(tok, tenant.slug), json={'row_version': 99, 'name': 'X'})
    assert r.status_code == 409, r.text
    assert r.json()['error']['code'] == 'record_changed'


def test_patch_name_clash(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_shift(db, name='Alpha')
    b = _mk_shift(db, name='Beta')
    r = client.patch(f'/api/v1/shifts/{b.id}', headers=_auth(tok, tenant.slug), json={'row_version': 1, 'name': 'alpha'})
    assert r.status_code == 409, r.text
    assert r.json()['error']['code'] == 'duplicate_name'


def test_patch_deactivate_reactivate(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    shift = _mk_shift(db)
    r1 = client.patch(f'/api/v1/shifts/{shift.id}', headers=_auth(tok, tenant.slug), json={'row_version': 1, 'is_active': False})
    assert r1.status_code == 200, r1.text
    assert r1.json()['is_active'] is False
    r2 = client.patch(f'/api/v1/shifts/{shift.id}', headers=_auth(tok, tenant.slug), json={'row_version': 2, 'is_active': True})
    assert r2.status_code == 200, r2.text
    assert r2.json()['is_active'] is True


def test_delete_unreferenced_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    shift = _mk_shift(db, name='Deletable')
    r = client.delete(f'/api/v1/shifts/{shift.id}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 204, r.text
    assert db.scalar(select(Shift).where(Shift.id == shift.id)) is None


def test_delete_in_use_409(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    shift = _mk_shift(db, name='InUse')
    _mk_rate_rule(db, shift.id)
    r = client.delete(f'/api/v1/shifts/{shift.id}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 409, r.text
    body = r.json()
    assert body['error']['code'] == 'shift_in_use'
    assert body['error']['details']['rate_rules'] == 1


def test_list_include_inactive(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_shift(db, name='Active')
    _mk_shift(db, name='Inactive', is_active=False)
    r1 = client.get('/api/v1/shifts', headers=_auth(tok, tenant.slug))
    assert r1.status_code == 200, r1.text
    names = {s['name'] for s in r1.json()['items']}
    assert 'Active' in names and 'Inactive' not in names
    r2 = client.get('/api/v1/shifts?include_inactive=true', headers=_auth(tok, tenant.slug))
    assert r2.status_code == 200, r2.text
    names2 = {s['name'] for s in r2.json()['items']}
    assert 'Active' in names2 and 'Inactive' in names2


def test_list_include_total(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_shift(db, name='A')
    _mk_shift(db, name='B')
    r = client.get('/api/v1/shifts?include_total=true', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    assert r.json()['total'] == 2

# END OF FILE
