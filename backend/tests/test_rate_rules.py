'''Shift rate rule endpoint tests (Chapter 2A).'''
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import select
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
        _drop_tenant_database, _tenant_db_name, provision_tenant,
    )
    slug = f'rules-{uuid.uuid4().hex[:10]}'
    result = provision_tenant(slug=slug, name='Rate Rules Test Co', admin_username='admin', admin_password_hash=hash_password('TestPassword123!'))
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


def _mk_shift(session, name='Default'):
    s = Shift(name=name, start_time=time(8, 0), length_minutes=480, unpaid_break_minutes=60, paid_break_minutes=0, grace_late_minutes=10, grace_early_minutes=5, rounding_minutes=5, rounding_mode='nearest', min_overtime_minutes=15, overtime_requires_approval=True, max_shift_minutes=720, match_tolerance_minutes=60, salaried_premium_mode='full')
    session.add(s)
    session.commit()
    return s


def _mk_rule(session, *, shift_id, day_type='weekday', kind='normal', tier=1, tier_up_to_minutes=None, method='multiplier', value=1.0, flat_unit=None, effective_from=None, effective_to=None):
    r = ShiftRateRule(shift_id=shift_id, day_type=day_type, kind=kind, tier=tier, tier_up_to_minutes=tier_up_to_minutes, method=method, value=value, flat_unit=flat_unit, effective_from=effective_from or date(2024, 1, 1), effective_to=effective_to)
    session.add(r)
    session.commit()
    return r


def test_list_requires_auth(api, db):
    client, tenant = api
    s = _mk_shift(db, name='NoAuth')
    r = client.get(f'/api/v1/shifts/{s.id}/rate-rules', headers={'X-Tenant-Slug': tenant.slug})
    assert r.status_code == 401, r.text


def test_list_payroll_admin_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    s = _mk_shift(db)
    _mk_rule(db, shift_id=s.id, tier=1, tier_up_to_minutes=30)
    _mk_rule(db, shift_id=s.id, tier=2, tier_up_to_minutes=None)
    r = client.get(f'/api/v1/shifts/{s.id}/rate-rules', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    assert len(r.json()['items']) == 2


def test_list_hr_forbidden(api, db):
    client, tenant = api
    _mk_user(db, username='hr-rules', role='hr', password='HrRulesPass123!')
    tok = _login(client, tenant.slug, 'hr-rules', 'HrRulesPass123!')
    s = _mk_shift(db)
    r = client.get(f'/api/v1/shifts/{s.id}/rate-rules', headers=_auth(tok, tenant.slug))
    assert r.status_code == 403, r.text


def test_list_filters_by_day_type(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    s = _mk_shift(db)
    _mk_rule(db, shift_id=s.id, day_type='weekday', tier=1, tier_up_to_minutes=None)
    _mk_rule(db, shift_id=s.id, day_type='saturday', tier=1, tier_up_to_minutes=None)
    r = client.get(f'/api/v1/shifts/{s.id}/rate-rules?day_type=saturday', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    items = r.json()['items']
    assert len(items) == 1 and items[0]['day_type'] == 'saturday'


def test_list_filters_by_effective_on(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    s = _mk_shift(db)
    _mk_rule(db, shift_id=s.id, tier=1, tier_up_to_minutes=None, effective_from=date(2024, 1, 1), effective_to=date(2024, 6, 30))
    _mk_rule(db, shift_id=s.id, tier=1, tier_up_to_minutes=None, effective_from=date(2024, 7, 1), effective_to=date(2024, 12, 31))
    r = client.get(f'/api/v1/shifts/{s.id}/rate-rules?effective_on=2024-08-15', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    assert len(r.json()['items']) == 1
    assert r.json()['items'][0]['effective_from'] == '2024-07-01'


def test_create_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    s = _mk_shift(db)
    payload = {'day_type': 'weekday', 'kind': 'normal', 'tier': 1, 'tier_up_to_minutes': None, 'method': 'multiplier', 'value': '1.0', 'effective_from': '2024-01-01'}
    r = client.post(f'/api/v1/shifts/{s.id}/rate-rules', headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['tier'] == 1
    assert float(body['value']) == 1.0


def test_create_non_contiguous_tiers(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    s = _mk_shift(db)
    _mk_rule(db, shift_id=s.id, tier=1, tier_up_to_minutes=30)
    payload = {'day_type': 'weekday', 'kind': 'normal', 'tier': 3, 'tier_up_to_minutes': None, 'method': 'multiplier', 'value': '2.0', 'effective_from': '2024-01-01'}
    r = client.post(f'/api/v1/shifts/{s.id}/rate-rules', headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 400, r.text
    assert r.json()['error']['code'] == 'invalid_tier_structure'


def test_create_no_top_tier(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    s = _mk_shift(db)
    _mk_rule(db, shift_id=s.id, tier=1, tier_up_to_minutes=30)
    _mk_rule(db, shift_id=s.id, tier=2, tier_up_to_minutes=60)
    payload = {'day_type': 'weekday', 'kind': 'normal', 'tier': 3, 'tier_up_to_minutes': 90, 'method': 'multiplier', 'value': '2.0', 'effective_from': '2024-01-01'}
    r = client.post(f'/api/v1/shifts/{s.id}/rate-rules', headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 400, r.text
    assert r.json()['error']['code'] == 'invalid_tier_structure'


def test_create_tier_up_to_not_increasing(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    s = _mk_shift(db)
    _mk_rule(db, shift_id=s.id, tier=1, tier_up_to_minutes=60)
    payload = {'day_type': 'weekday', 'kind': 'normal', 'tier': 2, 'tier_up_to_minutes': 30, 'method': 'multiplier', 'value': '1.5', 'effective_from': '2024-01-01'}
    r = client.post(f'/api/v1/shifts/{s.id}/rate-rules', headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 400, r.text
    assert r.json()['error']['code'] == 'invalid_tier_structure'


def test_create_overlapping_period(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    s = _mk_shift(db)
    _mk_rule(db, shift_id=s.id, tier=1, tier_up_to_minutes=None, effective_from=date(2024, 1, 1), effective_to=date(2024, 6, 30))
    payload = {'day_type': 'weekday', 'kind': 'normal', 'tier': 1, 'tier_up_to_minutes': None, 'method': 'multiplier', 'value': '1.5', 'effective_from': '2024-06-01', 'effective_to': '2024-12-31'}
    r = client.post(f'/api/v1/shifts/{s.id}/rate-rules', headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 409, r.text
    assert r.json()['error']['code'] == 'overlapping_rate_rule'


def test_create_multiplier_with_flat_unit_rejected(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    s = _mk_shift(db)
    payload = {'day_type': 'weekday', 'kind': 'normal', 'tier': 1, 'tier_up_to_minutes': None, 'method': 'multiplier', 'value': '1.5', 'flat_unit': 'per_hour', 'effective_from': '2024-01-01'}
    r = client.post(f'/api/v1/shifts/{s.id}/rate-rules', headers=_auth(tok, tenant.slug), json=payload)
    assert r.status_code == 422, r.text


def test_delete_future_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    s = _mk_shift(db)
    future = date.today() + timedelta(days=30)
    rule = _mk_rule(db, shift_id=s.id, tier=1, tier_up_to_minutes=None, effective_from=future)
    rule_id = rule.id
    r = client.delete(f'/api/v1/shifts/{s.id}/rate-rules/{rule.id}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 204, r.text
    db.expire_all()
    assert db.scalar(select(ShiftRateRule).where(ShiftRateRule.id == rule_id)) is None


def test_delete_past_409(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    s = _mk_shift(db)
    rule = _mk_rule(db, shift_id=s.id, tier=1, tier_up_to_minutes=None, effective_from=date(2024, 1, 1))
    r = client.delete(f'/api/v1/shifts/{s.id}/rate-rules/{rule.id}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 409, r.text
    assert r.json()['error']['code'] == 'rate_rule_in_use'


def test_delete_unknown_404(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    s = _mk_shift(db)
    r = client.delete(f'/api/v1/shifts/{s.id}/rate-rules/{uuid.uuid4()}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 404, r.text
    assert r.json()['error']['code'] == 'record_not_found'

# END OF FILE
