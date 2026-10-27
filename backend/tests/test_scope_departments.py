"""Department scope tests for app.core.scope (1C.7).

Table-driven. Expected results are plain test data in the parametrize table.
Rules under test (independent transcription, from 1C.7 decision 4):
  - payroll_admin, auditor, hr-without-scope: all departments.
  - hr-with-scope and manager: departments named by their department-type
    scope rows, plus the department on their own employee record.
    Branch- and site-type scope rows contribute nothing.
  - employee: only the department on their own employee record.
  - no linked employee and no scope rows: none.
  - unknown role: none.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.scope import (
    ScopeViolation,
    apply_department_scope,
    assert_department_in_scope,
)
from app.db.tenant.models.organisation import Branch, Department, Site
from app.db.tenant.models.people import Employee, User, UserScope
from app.db.tenant.session import get_tenant_engine


@dataclass
class _DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def disposable_tenant() -> Iterator[_DisposableTenant]:
    from app.core.security import hash_password
    from app.db.control.models import Subscriber
    from app.db.control.session import control_session
    from app.services.provisioning import (
        _drop_tenant_database,
        _tenant_db_name,
        provision_tenant,
    )

    slug = f"deptscope-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Dept Scope Co",
        admin_username="admin",
        admin_password_hash=hash_password("DeptScopePassword123!"),
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
            row = (
                session.query(Subscriber)
                .filter(Subscriber.slug == slug)
                .one_or_none()
            )
            if row is not None:
                session.delete(row)


def _mk_department(session: Session, name: str, *, parent_id=None) -> Department:
    d = Department(
        name=name,
        code=f"D-{uuid.uuid4().hex[:8]}",
        parent_id=parent_id,
        is_active=True,
        row_version=1,
    )
    session.add(d)
    session.flush()
    return d


def _mk_branch(session: Session, name: str) -> Branch:
    b = Branch(name=name, code=f"B-{uuid.uuid4().hex[:8]}", is_active=True, row_version=1)
    session.add(b)
    session.flush()
    return b


def _mk_site(session: Session, branch: Branch, name: str) -> Site:
    s = Site(
        branch_id=branch.id,
        name=name,
        code=f"S-{uuid.uuid4().hex[:8]}",
        site_type="site",
        timezone="Africa/Johannesburg",
        is_active=True,
        row_version=1,
    )
    session.add(s)
    session.flush()
    return s


def _mk_employee(
    session: Session,
    code: str,
    *,
    department_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
) -> Employee:
    e = Employee(
        employee_code=code,
        first_name="E",
        last_name=code,
        hire_date=date(2024, 1, 1),
        department_id=department_id,
        branch_id=branch_id,
        site_id=site_id,
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
    )
    session.add(e)
    session.flush()
    return e


def _mk_user(
    session: Session,
    username: str,
    role: str,
    *,
    employee_id: uuid.UUID | None = None,
) -> User:
    u = User(
        username=username,
        password_hash="x" * 60,
        role=role,
        is_active=True,
        must_change_password=False,
        employee_id=employee_id,
    )
    session.add(u)
    session.flush()
    return u


def _mk_scope(session: Session, user: User, scope_type: str, scope_id: uuid.UUID) -> None:
    session.add(UserScope(user_id=user.id, scope_type=scope_type, scope_id=scope_id))
    session.flush()


def _user(role: str, *, user_id=None, employee_id=None):
    return SimpleNamespace(role=role, id=user_id or uuid.uuid4(), employee_id=employee_id)


@pytest.fixture()
def branch_session(disposable_tenant) -> Iterator[Session]:
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()


@dataclass
class _Topology:
    d1: Department
    d2: Department
    d3: Department
    emp_in_d1: Employee
    emp_in_d2: Employee
    emp_in_d3: Employee
    mgr_in_d1: Employee


@pytest.fixture()
def topology(branch_session: Session) -> _Topology:
    d1 = _mk_department(branch_session, "engineering")
    d2 = _mk_department(branch_session, "finance")
    d3 = _mk_department(branch_session, "ops")
    emp_in_d1 = _mk_employee(branch_session, "E-D1", department_id=d1.id)
    emp_in_d2 = _mk_employee(branch_session, "E-D2", department_id=d2.id)
    emp_in_d3 = _mk_employee(branch_session, "E-D3", department_id=d3.id)
    mgr_in_d1 = _mk_employee(branch_session, "MGR-D1", department_id=d1.id)
    branch_session.commit()
    return _Topology(
        d1=d1, d2=d2, d3=d3,
        emp_in_d1=emp_in_d1, emp_in_d2=emp_in_d2, emp_in_d3=emp_in_d3,
        mgr_in_d1=mgr_in_d1,
    )


@pytest.mark.parametrize(
    "case_id,role,scope_rows,employee_attr,expected_attrs,expect_all",
    [
        ("payroll_admin--no-scopes", "payroll_admin", [], "emp_in_d1", ("d1", "d2", "d3"), True),
        ("auditor--no-scopes", "auditor", [], None, ("d1", "d2", "d3"), True),

        ("hr--no-scopes", "hr", [], "emp_in_d1", ("d1", "d2", "d3"), True),
        ("hr--dept-scope-d2--own-d1", "hr", [("department", "d2")], "emp_in_d1", ("d1", "d2"), False),
        # Branch-type scope rows contribute NO departments: only the caller's
        # own department (d1) survives.
        ("hr--branch-scope-only--own-d1", "hr", [("branch", "b1")], "emp_in_d1", ("d1",), False),
        # Site-type scope rows contribute NO departments: only own department.
        ("hr--site-scope-only--own-d1", "hr", [("site", "s1")], "emp_in_d1", ("d1",), False),
        # No employee record; dept-scope on d2 -> only d2.
        ("hr--dept-scope-d2--no-employee", "hr", [("department", "d2")], None, ("d2",), False),

        ("manager--no-scopes--own-d1", "manager", [], "mgr_in_d1", ("d1",), False),
        ("manager--dept-scope-d3--own-d1", "manager", [("department", "d3")], "mgr_in_d1", ("d1", "d3"), False),
        ("manager--branch-scope-only--own-d1", "manager", [("branch", "b1")], "mgr_in_d1", ("d1",), False),
        ("manager--no-employee--no-scopes", "manager", [], None, (), False),
        ("manager--no-employee--dept-scope-d2", "manager", [("department", "d2")], None, ("d2",), False),

        ("employee--own-d1", "employee", [], "emp_in_d1", ("d1",), False),
        ("employee--own-d3", "employee", [], "emp_in_d3", ("d3",), False),
        ("employee--no-employee-record", "employee", [], None, (), False),

        ("unknown-role", "intruder", [], "emp_in_d1", (), False),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_department_visibility(
    case_id, role, scope_rows, employee_attr, expected_attrs, expect_all,
    topology, branch_session
):
    # For branch- and site-type scope rows in the table, we need a real
    # branch and site to point at; they are created here to satisfy the FK.
    employee_id = getattr(topology, employee_attr).id if employee_attr else None
    db_user = _mk_user(branch_session, f"u-{case_id}", role, employee_id=employee_id)
    for scope_type, ref in scope_rows:
        if scope_type == "branch":
            b = _mk_branch(branch_session, f"b-{case_id}")
            _mk_scope(branch_session, db_user, "branch", b.id)
        elif scope_type == "site":
            b = _mk_branch(branch_session, f"b-{case_id}")
            s = _mk_site(branch_session, b, f"s-{case_id}")
            _mk_scope(branch_session, db_user, "site", s.id)
        elif scope_type == "department":
            _mk_scope(branch_session, db_user, "department", getattr(topology, ref).id)
    branch_session.commit()
    user = _user(role, user_id=db_user.id, employee_id=employee_id)

    expected = {getattr(topology, a).id for a in expected_attrs}
    q = apply_department_scope(select(Department.id), user, branch_session)
    visible = set(branch_session.scalars(q).all())

    if expect_all:
        assert visible == {topology.d1.id, topology.d2.id, topology.d3.id}
    else:
        assert visible == expected, f"case {case_id}: expected {expected}, got {visible}"


def test_assert_department_in_scope_payroll_admin_and_auditor(topology, branch_session):
    for role in ("payroll_admin", "auditor"):
        user = _user(role)
        for d in (topology.d1, topology.d2, topology.d3):
            assert_department_in_scope(user, d.id, branch_session)


def test_assert_department_in_scope_hr_without_scope_is_company_wide(topology, branch_session):
    db_user = _mk_user(branch_session, "hr-cw", "hr", employee_id=topology.emp_in_d1.id)
    branch_session.commit()
    user = _user("hr", user_id=db_user.id, employee_id=topology.emp_in_d1.id)
    for d in (topology.d1, topology.d2, topology.d3):
        assert_department_in_scope(user, d.id, branch_session)


def test_assert_department_in_scope_hr_with_dept_scope_is_restricted(topology, branch_session):
    db_user = _mk_user(branch_session, "hr-scoped", "hr", employee_id=topology.emp_in_d1.id)
    _mk_scope(branch_session, db_user, "department", topology.d2.id)
    branch_session.commit()
    user = _user("hr", user_id=db_user.id, employee_id=topology.emp_in_d1.id)

    assert_department_in_scope(user, topology.d2.id, branch_session)
    assert_department_in_scope(user, topology.d1.id, branch_session)
    with pytest.raises(ScopeViolation):
        assert_department_in_scope(user, topology.d3.id, branch_session)


def test_assert_department_in_scope_manager_cannot_guess_other_department(topology, branch_session):
    db_user = _mk_user(
        branch_session, "mgr-guess", "manager", employee_id=topology.mgr_in_d1.id
    )
    branch_session.commit()
    user = _user("manager", user_id=db_user.id, employee_id=topology.mgr_in_d1.id)

    assert_department_in_scope(user, topology.d1.id, branch_session)
    with pytest.raises(ScopeViolation):
        assert_department_in_scope(user, topology.d2.id, branch_session)


def test_assert_department_in_scope_employee_own_only(topology, branch_session):
    db_user = _mk_user(
        branch_session, "emp-scope", "employee", employee_id=topology.emp_in_d2.id
    )
    branch_session.commit()
    user = _user("employee", user_id=db_user.id, employee_id=topology.emp_in_d2.id)

    assert_department_in_scope(user, topology.d2.id, branch_session)
    with pytest.raises(ScopeViolation):
        assert_department_in_scope(user, topology.d1.id, branch_session)


def test_assert_department_in_scope_unknown_role_fails_closed(topology, branch_session):
    user = _user("intruder")
    for d in (topology.d1, topology.d2, topology.d3):
        with pytest.raises(ScopeViolation):
            assert_department_in_scope(user, d.id, branch_session)


def test_assert_department_in_scope_no_employee_no_scopes_fails_closed(topology, branch_session):
    db_user = _mk_user(branch_session, "mgr-empty", "manager", employee_id=None)
    branch_session.commit()
    user = _user("manager", user_id=db_user.id, employee_id=None)
    for d in (topology.d1, topology.d2, topology.d3):
        with pytest.raises(ScopeViolation):
            assert_department_in_scope(user, d.id, branch_session)

# END OF FILE