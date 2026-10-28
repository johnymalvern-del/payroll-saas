'''Employee work-pattern assignment tests (Chapter 2A).'''
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.usernames import normalise_username
from app.db.tenant.models.attendance import EmployeeWorkPattern, WorkPattern
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
    from app.services.provisioning import (
        _drop_tenant_database, _tenant_db_name, provision_tenant,
    )
    slug = f'ewp-{uuid.uuid4().hex[:10]}'
    result = provision_tenant(slug=slug, name='EWP Test Co', admin_username='admin', admin_password_hash=hash_password('TestPassword123!'))
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


def _mk_pattern(session, name):
    p = WorkPattern(name=name, cycle_length_days=7, anchor_date=date(2024, 1, 1), is_active=True, row_version=1)
    session.add(p)
    session.commit()
    return p


def _mk_assignment(session, *, employee_id, work_pattern_id, from_date, to_date=None):
    a = EmployeeWorkPattern(employee_id=employee_id, work_pattern_id=work_pattern_id, effective_from=from_date, effective_to=to_date)
    session.add(a)
    session.commit()
    return a


def test_list_requires_auth(api, db):
    client, tenant = api
    emp = _mk_employee(db, 'NA-1')
    r = client.get(f'/api/v1/employees/{emp.id}/work-patterns', headers={'X-Tenant-Slug': tenant.slug})
    assert r.status_code == 401, r.text


def test_list_admin_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp = _mk_employee(db, 'ADM-1')
    p = _mk_pattern(db, 'P1')
    _mk_assignment(db, employee_id=emp.id, work_pattern_id=p.id, from_date=date(2024, 1, 1))
    r = client.get(f'/api/v1/employees/{emp.id}/work-patterns', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text
    assert len(r.json()['items']) == 1


def test_list_employee_forbidden(api, db):
    client, tenant = api
    emp = _mk_employee(db, 'EMP-1')
    _mk_user(db, username='emp-x', role='employee', password='EmpPassword123!', employee_id=emp.id)
    tok = _login(client, tenant.slug, 'emp-x', 'EmpPassword123!')
    r = client.get(f'/api/v1/employees/{emp.id}/work-patterns', headers=_auth(tok, tenant.slug))
    assert r.status_code == 403, r.text


def test_list_hr_ok(api, db):
    client, tenant = api
    _mk_user(db, username='hr-x', role='hr', password='HrPassword12345!')
    tok = _login(client, tenant.slug, 'hr-x', 'HrPassword12345!')
    emp = _mk_employee(db, 'HR-1')
    r = client.get(f'/api/v1/employees/{emp.id}/work-patterns', headers=_auth(tok, tenant.slug))
    assert r.status_code == 200, r.text


def test_list_unknown_employee_404(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    r = client.get(f'/api/v1/employees/{uuid.uuid4()}/work-patterns', headers=_auth(tok, tenant.slug))
    assert r.status_code == 404, r.text


def test_list_out_of_scope_hr_returns_404(api, db):
    client, tenant = api
    from app.db.tenant.models.organisation import Branch
    from app.db.tenant.models.people import UserScope
    b1 = Branch(name='B1-OOS', code='B1-OOS', is_active=True, row_version=1)
    db.add(b1)
    db.commit()
    hr_u = _mk_user(db, username='hr-oos', role='hr', password='HrOosPassword123!')
    db.add(UserScope(user_id=hr_u.id, scope_type='branch', scope_id=b1.id))
    db.commit()
    emp = _mk_employee(db, 'OOS-1')
    tok = _login(client, tenant.slug, 'hr-oos', 'HrOosPassword123!')
    r = client.get(f'/api/v1/employees/{emp.id}/work-patterns', headers=_auth(tok, tenant.slug))
    assert r.status_code == 404, r.text


def test_create_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp = _mk_employee(db, 'C-1')
    p = _mk_pattern(db, 'P-C')
    r = client.post(f'/api/v1/employees/{emp.id}/work-patterns', headers=_auth(tok, tenant.slug), json={'work_pattern_id': str(p.id), 'effective_from': '2024-01-01'})
    assert r.status_code == 201, r.text
    assert r.json()['work_pattern_id'] == str(p.id)


def test_create_invalid_pattern_400(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp = _mk_employee(db, 'C-2')
    r = client.post(f'/api/v1/employees/{emp.id}/work-patterns', headers=_auth(tok, tenant.slug), json={'work_pattern_id': str(uuid.uuid4()), 'effective_from': '2024-01-01'})
    assert r.status_code == 400, r.text
    assert r.json()['error']['code'] == 'invalid_work_pattern'


def test_create_overlapping_409(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp = _mk_employee(db, 'C-3')
    p = _mk_pattern(db, 'P-O')
    _mk_assignment(db, employee_id=emp.id, work_pattern_id=p.id, from_date=date(2024, 1, 1), to_date=date(2024, 6, 30))
    r = client.post(f'/api/v1/employees/{emp.id}/work-patterns', headers=_auth(tok, tenant.slug), json={'work_pattern_id': str(p.id), 'effective_from': '2024-06-01', 'effective_to': '2024-12-31'})
    assert r.status_code == 409, r.text
    assert r.json()['error']['code'] == 'overlapping_period'


def test_create_adjacent_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp = _mk_employee(db, 'C-4')
    p = _mk_pattern(db, 'P-A')
    _mk_assignment(db, employee_id=emp.id, work_pattern_id=p.id, from_date=date(2024, 1, 1), to_date=date(2024, 6, 30))
    r = client.post(f'/api/v1/employees/{emp.id}/work-patterns', headers=_auth(tok, tenant.slug), json={'work_pattern_id': str(p.id), 'effective_from': '2024-07-01'})
    assert r.status_code == 201, r.text


def test_end_ok(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp = _mk_employee(db, 'E-1')
    p = _mk_pattern(db, 'P-E')
    a = _mk_assignment(db, employee_id=emp.id, work_pattern_id=p.id, from_date=date(2024, 1, 1))
    r = client.patch(f'/api/v1/employees/{emp.id}/work-patterns/{a.id}', headers=_auth(tok, tenant.slug), json={'effective_to': '2024-06-30'})
    assert r.status_code == 200, r.text
    assert r.json()['effective_to'] == '2024-06-30'


def test_end_invalid_to_400(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp = _mk_employee(db, 'E-2')
    p = _mk_pattern(db, 'P-E2')
    a = _mk_assignment(db, employee_id=emp.id, work_pattern_id=p.id, from_date=date(2024, 6, 1))
    r = client.patch(f'/api/v1/employees/{emp.id}/work-patterns/{a.id}', headers=_auth(tok, tenant.slug), json={'effective_to': '2024-05-01'})
    assert r.status_code == 400, r.text


def test_end_overlap_409(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    emp = _mk_employee(db, 'E-3')
    p = _mk_pattern(db, 'P-E3')
    a1 = _mk_assignment(db, employee_id=emp.id, work_pattern_id=p.id, from_date=date(2024, 1, 1))
    _mk_assignment(db, employee_id=emp.id, work_pattern_id=p.id, from_date=date(2024, 6, 1), to_date=date(2024, 12, 31))
    r = client.patch(f'/api/v1/employees/{emp.id}/work-patterns/{a1.id}', headers=_auth(tok, tenant.slug), json={'effective_to': '2024-08-01'})
    assert r.status_code == 409, r.text
    assert r.json()['error']['code'] == 'overlapping_period'

# END OF FILE
