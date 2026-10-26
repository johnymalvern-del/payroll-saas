"""Branch scope tests for app.core.scope (1C.4.1).

Table-driven. Every expected result is written as plain test data in the
parametrize table below; nothing in this file recomputes what the code under
test computes. The expected branch ids are fixed by the fixtures, so a bug
in `_scoped_branch_ids` cannot quietly pass by agreeing with a bug in the
test.

The `disposable_tenant` fixture is duplicated from tests/test_permissions.py.
TODO: promote to conftest.py in a cleanup reply.
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
    apply_branch_scope,
    assert_branch_in_scope,
)
from app.db.tenant.models.organisation import Branch, Site
from app.db.tenant.models.people import Employee, User, UserScope
from app.db.tenant.session import get_tenant_engine


# ---------------------------------------------------------------------------
# disposable_tenant fixture (duplicated from tests/test_permissions.py).
# TODO: promote to conftest.py in a cleanup reply.
# ---------------------------------------------------------------------------


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

    slug = f"brscope-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Branch Scope Co",
        admin_username="admin",
        admin_password_hash=hash_password("BranchScopePassword123!"),
    )
    db_name = _tenant_db_name(slug)
    try:
        yield _DisposableTenant(
            slug=result.slug,
            tenant_db_name=result.tenant_db_name,
            subscriber_id=result.subscriber_id,
        )
    finally:
        _drop_tenant_database(db_name)
        with control_session() as session:
            row = (
                session.query(Subscriber)
                .filter(Subscriber.slug == slug)
                .one_or_none()
            )
            if row is not None:
                session.delete(row)


# ---------------------------------------------------------------------------
# Small factories. No helper here derives an expected value from the code
# under test; every value is either a fresh uuid or a fixed string.
# ---------------------------------------------------------------------------


def _mk_branch(session: Session, name: str) -> Branch:
    b = Branch(name=name, code=f"B-{uuid.uuid4().hex[:8]}")
    session.add(b)
    session.flush()
    return b


def _mk_site(session: Session, branch: Branch, name: str) -> Site:
    s = Site(branch_id=branch.id, name=name, code=f"S-{uuid.uuid4().hex[:8]}")
    session.add(s)
    session.flush()
    return s


def _mk_employee(
    session: Session,
    code: str,
    *,
    branch_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    manager_id: uuid.UUID | None = None,
) -> Employee:
    e = Employee(
        employee_code=code,
        first_name="E",
        last_name=code,
        hire_date=date(2024, 1, 1),
        branch_id=branch_id,
        site_id=site_id,
        manager_id=manager_id,
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


def _select_all_branch_ids(session: Session):
    return select(Branch).order_by(Branch.id)


def _resolved_ids(session: Session, user) -> set[uuid.UUID] | None:
    """Return the set of branch ids visible to `user`, or None for all.

    Implementation is deliberately *not* read from `_scoped_branch_ids`
    (that is the code under test). Instead it runs the same query the real
    callers will run, via `apply_branch_scope`, against every branch in the
    database. That way a bug in `apply_branch_scope` cannot be masked.
    """
    all_ids = set(session.scalars(select(Branch.id)).all())
    if not all_ids:
        return None if _is_all(user) else set()
    q = apply_branch_scope(select(Branch.id), user, session)
    visible = set(session.scalars(q).all())
    # Detect the "no filter applied" case: every branch is visible and
    # `apply_branch_scope` returned the query unchanged. We cannot ask it,
    # so we treat full-visibility + company-wide role as "all", and
    # full-visibility for a scoped role as "all" only if the role should
    # see all. This is why every parametrized case pins the expected value
    # explicitly.
    if visible == all_ids:
        return None if _is_all(user) else all_ids
    return visible


def _is_all(user) -> bool:
    """The rule for "company-wide", stated independently of the code under test.

    Per 1C.4.1 rules: payroll_admin and auditor always see all. hr sees all
    only when the user has no user_scope rows. Every other case is scoped.
    """
    role = getattr(user, "role", None)
    if role in ("payroll_admin", "auditor"):
        return True
    return False


# ---------------------------------------------------------------------------
# Fixture data used by the parametrized cases.
#
# Branch topology:
#   B1 (alpha)  <-- S1, employee ownsit belongs here
#   B2 (beta)
#   B3 (gamma)  <-- S3
# ---------------------------------------------------------------------------


@dataclass
class _Topology:
    b1: Branch
    b2: Branch
    b3: Branch
    s1: Site  # under b1
    s3: Site  # under b3
    emp_in_b1: Employee
    emp_in_b3: Employee
    mgr_in_b1: Employee
    report_in_b2: Employee


@pytest.fixture()
def topology(branch_session: Session) -> _Topology:
    b1 = _mk_branch(branch_session, "alpha")
    b2 = _mk_branch(branch_session, "beta")
    b3 = _mk_branch(branch_session, "gamma")
    s1 = _mk_site(branch_session, b1, "site-1")
    s3 = _mk_site(branch_session, b3, "site-3")
    emp_in_b1 = _mk_employee(branch_session, "EMP-B1", branch_id=b1.id)
    emp_in_b3 = _mk_employee(branch_session, "EMP-B3", branch_id=b3.id)
    mgr_in_b1 = _mk_employee(branch_session, "MGR-B1", branch_id=b1.id)
    report_in_b2 = _mk_employee(
        branch_session, "REP-B2", branch_id=b2.id, manager_id=mgr_in_b1.id
    )
    branch_session.commit()
    return _Topology(
        b1=b1, b2=b2, b3=b3, s1=s1, s3=s3,
        emp_in_b1=emp_in_b1, emp_in_b3=emp_in_b3,
        mgr_in_b1=mgr_in_b1, report_in_b2=report_in_b2,
    )


# ---------------------------------------------------------------------------
# Parametrized visibility cases.
#
# Each case returns the branch ids that MUST be visible to the user. The
# tuple of attribute names ('b1','b2','b3') is looked up on `topology` in
# the test body, so the expected set is expressed in fixture terms, not in
# code terms.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case_id,role,scope_rows,employee_attr,expected_attrs,expect_all",
    [
        # payroll_admin and auditor: always all branches.
        ("payroll_admin--no-scopes", "payroll_admin", [], "emp_in_b1", ("b1", "b2", "b3"), True),
        ("auditor--no-scopes", "auditor", [], None, ("b1", "b2", "b3"), True),

        # hr: no scope rows -> all.
        ("hr--no-scopes", "hr", [], "emp_in_b1", ("b1", "b2", "b3"), True),
        # hr: branch scope row -> exactly that branch, plus own employee's branch
        # (which in this case is the same branch, so the set is unchanged).
        ("hr--branch-scope-on-b1", "hr", [("branch", "b1")], "emp_in_b1", ("b1",), False),
        # hr: branch scope row for b2, but own employee is in b1, so both
        # branches are visible. This is a rule case, not a code-shape case.
        ("hr--branch-scope-on-b2--own-branch-b1", "hr", [("branch", "b2")], "emp_in_b1", ("b1", "b2"), False),
        # hr: site scope row for s3 -> branch b3, plus own branch b1.
        ("hr--site-scope-on-s3--own-branch-b1", "hr", [("site", "s3")], "emp_in_b1", ("b1", "b3"), False),
        # hr: department scope row only -> contributes no branch, but own
        # employee's branch b1 is included. Net: only b1.
        ("hr--dept-scope-only--own-branch-b1", "hr", [("department", "unused")], "emp_in_b1", ("b1",), False),
        # hr with scopes and no linked employee -> only resolved scope branches.
        ("hr--branch-scope-on-b3--no-employee", "hr", [("branch", "b3")], None, ("b3",), False),

        # manager: no scope rows, has employee in b1, has report in b2.
        # Direct reports do not add branches (per 1C.4.1 rule), so only b1.
        ("manager--no-scopes--own-branch-b1", "manager", [], "mgr_in_b1", ("b1",), False),
        # manager: branch scope on b3, own employee in b1 -> b1 + b3.
        ("manager--branch-scope-on-b3", "manager", [("branch", "b3")], "mgr_in_b1", ("b1", "b3"), False),
        # manager: site scope on s1 -> branch b1, own employee also b1.
        ("manager--site-scope-on-s1", "manager", [("site", "s1")], "mgr_in_b1", ("b1",), False),
        # manager: no employee record and no scopes -> empty.
        ("manager--no-employee--no-scopes", "manager", [], None, (), False),
        # manager: scope rows but no employee record -> only the resolved
        # scope branch (b2).
        ("manager--no-employee--branch-scope-on-b2", "manager", [("branch", "b2")], None, ("b2",), False),

        # employee: own branch only.
        ("employee--own-branch-b1", "employee", [], "emp_in_b1", ("b1",), False),
        ("employee--own-branch-b3", "employee", [], "emp_in_b3", ("b3",), False),
        # employee with no linked employee record -> empty.
        ("employee--no-employee-record", "employee", [], None, (), False),

        # unknown role -> empty, regardless of scope rows.
        ("unknown-role", "intruder", [], "emp_in_b1", (), False),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_branch_visibility(
    case_id, role, scope_rows, employee_attr, expected_attrs, expect_all, topology, branch_session
):
    employee_id = getattr(topology, employee_attr).id if employee_attr else None
    user = _user(role, employee_id=employee_id)
    # Persist the user and any scope rows so _scoped_branch_ids can read them.
    db_user = _mk_user(branch_session, f"u-{case_id}", role, employee_id=employee_id)
    for scope_type, ref in scope_rows:
        if scope_type == "department":
            # Any uuid will do: departments are not consulted for branches.
            _mk_scope(branch_session, db_user, "department", uuid.uuid4())
        else:
            _mk_scope(branch_session, db_user, scope_type, getattr(topology, ref).id)
    branch_session.commit()
    user.id = db_user.id

    expected = {getattr(topology, a).id for a in expected_attrs}

    q = apply_branch_scope(select(Branch.id), user, branch_session)
    visible = set(branch_session.scalars(q).all())

    if expect_all:
        assert visible == {topology.b1.id, topology.b2.id, topology.b3.id}
    else:
        assert visible == expected, f"case {case_id}: expected {expected}, got {visible}"


# ---------------------------------------------------------------------------
# assert_branch_in_scope: positive, negative, and UUID-guessing cases.
# ---------------------------------------------------------------------------


def test_assert_branch_in_scope_payroll_admin_always_ok(topology, branch_session):
    user = _user("payroll_admin")
    for b in (topology.b1, topology.b2, topology.b3):
        assert_branch_in_scope(user, b.id, branch_session)


def test_assert_branch_in_scope_auditor_always_ok(topology, branch_session):
    user = _user("auditor")
    for b in (topology.b1, topology.b2, topology.b3):
        assert_branch_in_scope(user, b.id, branch_session)


def test_assert_branch_in_scope_hr_without_scope_is_company_wide(topology, branch_session):
    hr_emp = topology.emp_in_b1
    db_user = _mk_user(branch_session, "hr-cw", "hr", employee_id=hr_emp.id)
    branch_session.commit()
    user = _user("hr", user_id=db_user.id, employee_id=hr_emp.id)
    for b in (topology.b1, topology.b2, topology.b3):
        assert_branch_in_scope(user, b.id, branch_session)


def test_assert_branch_in_scope_hr_with_branch_scope_is_restricted(topology, branch_session):
    hr_emp = topology.emp_in_b1
    db_user = _mk_user(branch_session, "hr-scoped", "hr", employee_id=hr_emp.id)
    _mk_scope(branch_session, db_user, "branch", topology.b2.id)
    branch_session.commit()
    user = _user("hr", user_id=db_user.id, employee_id=hr_emp.id)

    # b2 (explicit scope) and b1 (own employee) are in scope.
    assert_branch_in_scope(user, topology.b2.id, branch_session)
    assert_branch_in_scope(user, topology.b1.id, branch_session)
    # b3 is out of scope.
    with pytest.raises(ScopeViolation):
        assert_branch_in_scope(user, topology.b3.id, branch_session)


def test_assert_branch_in_scope_manager_cannot_guess_other_branch(topology, branch_session):
    mgr_emp = topology.mgr_in_b1
    db_user = _mk_user(branch_session, "mgr-guess", "manager", employee_id=mgr_emp.id)
    branch_session.commit()
    user = _user("manager", user_id=db_user.id, employee_id=mgr_emp.id)

    assert_branch_in_scope(user, topology.b1.id, branch_session)
    with pytest.raises(ScopeViolation):
        assert_branch_in_scope(user, topology.b2.id, branch_session)
    with pytest.raises(ScopeViolation):
        assert_branch_in_scope(user, topology.b3.id, branch_session)


def test_assert_branch_in_scope_employee_own_only(topology, branch_session):
    emp = topology.emp_in_b3
    db_user = _mk_user(branch_session, "emp-scope", "employee", employee_id=emp.id)
    branch_session.commit()
    user = _user("employee", user_id=db_user.id, employee_id=emp.id)

    assert_branch_in_scope(user, topology.b3.id, branch_session)
    with pytest.raises(ScopeViolation):
        assert_branch_in_scope(user, topology.b1.id, branch_session)


def test_assert_branch_in_scope_unknown_role_fails_closed(topology, branch_session):
    user = _user("intruder")
    for b in (topology.b1, topology.b2, topology.b3):
        with pytest.raises(ScopeViolation):
            assert_branch_in_scope(user, b.id, branch_session)


def test_assert_branch_in_scope_no_employee_no_scopes_fails_closed(topology, branch_session):
    # A manager with no employee record and no scope rows sees no branches.
    db_user = _mk_user(branch_session, "mgr-empty", "manager", employee_id=None)
    branch_session.commit()
    user = _user("manager", user_id=db_user.id, employee_id=None)
    for b in (topology.b1, topology.b2, topology.b3):
        with pytest.raises(ScopeViolation):
            assert_branch_in_scope(user, b.id, branch_session)