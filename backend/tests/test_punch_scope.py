"""Punch scope tests (Chapter 2A, A10).

Section 6 grants attendance view to employee (own), manager (in scope),
hr (scope rules), payroll_admin; NOT to auditor.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.usernames import normalise_username
from app.db.tenant.models.attendance import Punch
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
    from app.services.provisioning import _drop_tenant_database, _tenant_db_name, provision_tenant
    slug = f'pscope-{uuid.uuid4().hex[:10]}'
    result = provision_tenant(slug=slug, name='PunchScope Test', admin_username='admin', admin_password_hash=hash_password('TestPassword123!'))
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


def _mk_user(session, *, username, role, password, employee_id=None):
    u = User(username=normalise_username(username), password_hash=hash_password(password), role=role, is_active=True, must_change_password=False, employee_id=employee_id, row_version=1)
    session.add(u)
    session.commit()
    return u


def _mk_employee(session, code):
    e = Employee(employee_code=code, first_name='A', last_name='B', hire_date=date(2024, 1, 1), status='active', employee_type='hourly', pay_basis='hourly', pay_frequency='monthly', row_version=1)
    session.add(e)
    session.commit()
    return e


def _mk_punch(session, *, employee_id):
    now = datetime.now(timezone.utc)
    p = Punch(client_punch_id=uuid.uuid4(), payload_hash='0' * 64, employee_id=employee_id, device_id=None, site_id=None, device_time=now, effective_time=now, offset_ms=0, method='fingerprint', status='accepted', flags=[], raw_payload={})
    session.add(p)
    session.commit()
    return p


def test_employee_can_see_own_punches(api, db):
    client, tenant = api
    emp = _mk_employee(db, 'SELF-1')
    _mk_punch(db, employee_id=emp.id)
    _mk_user(db, username='self-u', role='employee', password='SelfUPassword1234!', employee_id=emp.id)
    tok = _login(client, tenant.slug, 'self-u', 'SelfUPassword1234!')
    r = client.get('/api/v1/punches', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    items = r.json()['items']
    assert len(items) == 1
    assert items[0]['employee_id'] == str(emp.id)


def test_employee_cannot_see_other_employee_punches(api, db):
    client, tenant = api
    me = _mk_employee(db, 'SELF-2')
    other = _mk_employee(db, 'OTHER-2')
    _mk_punch(db, employee_id=other.id)
    _mk_user(db, username='self-v', role='employee', password='SelfVPassword1234!', employee_id=me.id)
    tok = _login(client, tenant.slug, 'self-v', 'SelfVPassword1234!')
    r = client.get('/api/v1/punches', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    assert r.json()['items'] == []


def test_manager_outside_scope_gets_none(api, db):
    client, tenant = api
    mgr = _mk_employee(db, 'MGR-OUT')
    other = _mk_employee(db, 'OUT-EMP')
    _mk_punch(db, employee_id=other.id)
    _mk_user(db, username='mgr-out', role='manager', password='MgrOutPassword123!', employee_id=mgr.id)
    tok = _login(client, tenant.slug, 'mgr-out', 'MgrOutPassword123!')
    r = client.get('/api/v1/punches', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    assert r.json()['items'] == []


def test_guessed_punch_id_outside_scope_fails(api, db):
    client, tenant = api
    me = _mk_employee(db, 'GUESS-1')
    other = _mk_employee(db, 'GUESS-2')
    other_punch = _mk_punch(db, employee_id=other.id)
    _mk_user(db, username='guess-u', role='employee', password='GuessUPassword1234!', employee_id=me.id)
    tok = _login(client, tenant.slug, 'guess-u', 'GuessUPassword1234!')
    r = client.get(f'/api/v1/punches/{other_punch.id}', headers=_auth(tok, tenant.slug))
    assert r.status_code == 404, r.text
    assert r.json()['error']['code'] == 'record_not_found'


def test_auditor_cannot_access_punch_list(api, db):
    client, tenant = api
    _mk_user(db, username='aud-pscope', role='auditor', password='AudPscope12345!')
    tok = _login(client, tenant.slug, 'aud-pscope', 'AudPscope12345!')
    r = client.get('/api/v1/punches', headers=_auth(tok, tenant.slug))
    assert r.status_code == 403, r.text

# END OF FILE
