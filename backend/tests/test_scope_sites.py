"""Site scope tests for app.core.scope (1C.6).

Table-driven. Every expected result is plain test data in the parametrize
table; nothing here recomputes what the code under test computes. The
`disposable_tenant` fixture is declared locally so this module does not
depend on tests/tenancy/conftest.py (a sibling directory, not an ancestor).

Site scope rules (independent transcription, from 1C.6 acceptance):
  - payroll_admin, auditor, hr-without-scope: all sites.
  - hr-with-scope and manager: sites named by their site-type scope rows,
    plus sites inside any branch named by their branch-type scope rows,
    plus the site on their own employee record.
  - employee: only the site on their own employee record.
  - user with no linked employee and no scope rows: none.
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
    apply_site_scope,
    assert_site_in_scope,
)
from app.db.tenant.models.organisation import Branch, Site
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

    slug = f"sitescope-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Site Scope Co",
        admin_username="admin",
        admin_password_hash=hash_password("SiteScopePassword123!"),
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
    branch_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
) -> Employee:
    e = Employee(
        employee_code=code,
        first_name="E",
        last_name=code,
        hire_date=date(2024, 1, 1),
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
    b1: Branch
    b2: Branch
    s1: Site
    s2: Site
    s3: Site  # under b1
    emp_in_s1: Employee
    emp_in_s2: Employee
    emp_in_s3: Employee
    mgr_in_s1: Employee


@pytest.fixture()
def topology(branch_session: Session) -> _Topology:
    b1 = _mk_branch(branch_session, "beta-1")
    b2 = _mk_branch(branch_session, "beta-2")
    s1 = _mk_site(branch_session, b1, "s1")
    s2 = _mk_site(branch_session, b2, "s2")
    s3 = _mk_site(branch_session, b1, "s3")
    emp_in_s1 = _mk_employee(branch_session, "E-S1", branch_id=b1.id, site_id=s1.id)
    emp_in_s2 = _mk_employee(branch_session, "E-S2", branch_id=b2.id, site_id=s2.id)
    emp_in_s3 = _mk_employee(branch_session, "E-S3", branch_id=b1.id, site_id=s3.id)
    mgr_in_s1 = _mk_employee(branch_session, "MGR-S1", branch_id=b1.id, site_id=s1.id)
    branch_session.commit()
    return _Topology(
        b1=b1, b2=b2, s1=s1, s2=s2, s3=s3,
        emp_in_s1=emp_in_s1, emp_in_s2=emp_in_s2, emp_in_s3=emp_in_s3,
        mgr_in_s1=mgr_in_s1,
    )


@pytest.mark.parametrize(
    "case_id,role,scope_rows,employee_attr,expected_attrs,expect_all",
    [
        # payroll_admin and auditor: always all.
        ("payroll_admin--no-scopes", "payroll_admin", [], "emp_in_s1", ("s1", "s2", "s3"), True),
        ("auditor--no-scopes", "auditor", [], None, ("s1", "s2", "s3"), True),

        # hr no scopes -> all.
        ("hr--no-scopes", "hr", [], "emp_in_s1", ("s1", "s2", "s3"), True),
        # hr site-scope on s2 -> s2 + own site s1.
        ("hr--site-scope-s2--own-s1", "hr", [("site", "s2")], "emp_in_s1", ("s1", "s2"), False),
        # hr branch-scope on b2 -> s2 + own site s1.
        ("hr--branch-scope-b2--own-s1", "hr", [("branch", "b2")], "emp_in_s1", ("s1", "s2"), False),
        # hr branch-scope on b1 -> s1 + s3 + own s1.
        ("hr--branch-scope-b1--own-s1", "hr", [("branch", "b1")], "emp_in_s1", ("s1", "s3"), False),
        # hr department-scope only -> just own site s1.
        ("hr--dept-scope-only--own-s1", "hr", [("department", "unused")], "emp_in_s1", ("s1",), False),
        # hr with scope on s2 and no employee record -> only s2.
        ("hr--site-scope-s2--no-employee", "hr", [("site", "s2")], None, ("s2",), False),

        # manager no scopes -> only own site.
        ("manager--no-scopes--own-s1", "manager", [], "mgr_in_s1", ("s1",), False),
        # manager site-scope on s2 -> s2 + own s1.
        ("manager--site-scope-s2", "manager", [("site", "s2")], "mgr_in_s1", ("s1", "s2"), False),
        # manager branch-scope on b2 -> s2 + own s1.
        ("manager--branch-scope-b2", "manager", [("branch", "b2")], "mgr_in_s1", ("s1", "s2"), False),
        # manager no employee and no scopes -> none.
        ("manager--no-employee--no-scopes", "manager", [], None, (), False),
        # manager no employee but branch-scope b2 -> only s2.
        ("manager--no-employee--branch-scope-b2", "manager", [("branch", "b2")], None, ("s2",), False),

        # employee own site only.
        ("employee--own-s1", "employee", [], "emp_in_s1", ("s1",), False),
        ("employee--own-s3", "employee", [], "emp_in_s3", ("s3",), False),
        ("employee--no-employee-record", "employee", [], None, (), False),

        # unknown role -> none.
        ("unknown-role", "intruder", [], "emp_in_s1", (), False),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_site_visibility(
    case_id, role, scope_rows, employee_attr, expected_attrs, expect_all, topology, branch_session
):
    employee_id = getattr(topology, employee_attr).id if employee_attr else None
    db_user = _mk_user(branch_session, f"u-{case_id}", role, employee_id=employee_id)
    for scope_type, ref in scope_rows:
        if scope_type == "department":
            _mk_scope(branch_session, db_user, "department", uuid.uuid4())
        else:
            _mk_scope(branch_session, db_user, scope_type, getattr(topology, ref).id)
    branch_session.commit()
    user = _user(role, user_id=db_user.id, employee_id=employee_id)

    expected = {getattr(topology, a).id for a in expected_attrs}
    q = apply_site_scope(select(Site.id), user, branch_session)
    visible = set(branch_session.scalars(q).all())

    if expect_all:
        assert visible == {topology.s1.id, topology.s2.id, topology.s3.id}
    else:
        assert visible == expected, f"case {case_id}: expected {expected}, got {visible}"


def test_assert_site_in_scope_payroll_admin_and_auditor(topology, branch_session):
    for role in ("payroll_admin", "auditor"):
        user = _user(role)
        for s in (topology.s1, topology.s2, topology.s3):
            assert_site_in_scope(user, s.id, branch_session)


def test_assert_site_in_scope_hr_without_scope_is_company_wide(topology, branch_session):
    db_user = _mk_user(branch_session, "hr-cw", "hr", employee_id=topology.emp_in_s1.id)
    branch_session.commit()
    user = _user("hr", user_id=db_user.id, employee_id=topology.emp_in_s1.id)
    for s in (topology.s1, topology.s2, topology.s3):
        assert_site_in_scope(user, s.id, branch_session)


def test_assert_site_in_scope_hr_with_site_scope_is_restricted(topology, branch_session):
    db_user = _mk_user(branch_session, "hr-scoped", "hr", employee_id=topology.emp_in_s1.id)
    _mk_scope(branch_session, db_user, "site", topology.s2.id)
    branch_session.commit()
    user = _user("hr", user_id=db_user.id, employee_id=topology.emp_in_s1.id)

    assert_site_in_scope(user, topology.s2.id, branch_session)
    assert_site_in_scope(user, topology.s1.id, branch_session)
    with pytest.raises(ScopeViolation):
        assert_site_in_scope(user, topology.s3.id, branch_session)


def test_assert_site_in_scope_manager_cannot_guess_other_site(topology, branch_session):
    db_user = _mk_user(
        branch_session, "mgr-guess", "manager", employee_id=topology.mgr_in_s1.id
    )
    branch_session.commit()
    user = _user("manager", user_id=db_user.id, employee_id=topology.mgr_in_s1.id)

    assert_site_in_scope(user, topology.s1.id, branch_session)
    with pytest.raises(ScopeViolation):
        assert_site_in_scope(user, topology.s2.id, branch_session)
    with pytest.raises(ScopeViolation):
        assert_site_in_scope(user, topology.s3.id, branch_session)


def test_assert_site_in_scope_employee_own_only(topology, branch_session):
    db_user = _mk_user(
        branch_session, "emp-scope", "employee", employee_id=topology.emp_in_s2.id
    )
    branch_session.commit()
    user = _user("employee", user_id=db_user.id, employee_id=topology.emp_in_s2.id)

    assert_site_in_scope(user, topology.s2.id, branch_session)
    with pytest.raises(ScopeViolation):
        assert_site_in_scope(user, topology.s1.id, branch_session)


def test_assert_site_in_scope_unknown_role_fails_closed(topology, branch_session):
    user = _user("intruder")
    for s in (topology.s1, topology.s2, topology.s3):
        with pytest.raises(ScopeViolation):
            assert_site_in_scope(user, s.id, branch_session)


def test_assert_site_in_scope_no_employee_no_scopes_fails_closed(topology, branch_session):
    db_user = _mk_user(branch_session, "mgr-empty", "manager", employee_id=None)
    branch_session.commit()
    user = _user("manager", user_id=db_user.id, employee_id=None)
    for s in (topology.s1, topology.s2, topology.s3):
        with pytest.raises(ScopeViolation):
            assert_site_in_scope(user, s.id, branch_session)

# END OF FILE