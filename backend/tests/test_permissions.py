"""Permission matrix, scope semantics, and route-inventory tests.

The matrix below is written out independently of ROLE_PERMISSIONS. It is the
literal transcription of section 6 of the master brief. If the code and this
matrix disagree, one of them is wrong and the test fails.

The three Biometric Attendance Programme permissions (ATTENDANCE_CLOCK,
BIOMETRIC_ENROL, DEVICE_MANAGE) are not part of section 6 -- they extend it.
They are listed here in the same independent-transcription style so the
same guarantee holds: code and test must agree.

NOTE: SECTION_6_MATRIX does not enumerate every Permission. PAYSLIP_VIEW and
EMPLOYEE_CRUD are absent, a pre-existing gap in this file rather than an
intentional exclusion. There is deliberately no "matrix covers every
Permission" assertion, because adding one would fail on those two and
inventing their rows would put unverified content into a document that
claims to be a literal transcription.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute

from app.core.permissions import ROLE_PERMISSIONS, Permission, check_permission
from app.core.scope import ScopeViolation, assert_in_scope
from app.main import app


# ---------------------------------------------------------------------------
# Local disposable_tenant fixture.
#
# This test module lives at backend/tests/ (not backend/tests/tenancy/), so
# the tenancy-level conftest is not in scope. Define the fixture here.
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

    slug = f"perm-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Perm Test Co",
        admin_username="admin",
        admin_password_hash=hash_password("PermTestPassword123!"),
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
# Independent transcription of the section-6 matrix, plus the biometric
# attendance programme extensions.
# ---------------------------------------------------------------------------

ALL_ROLES = ("employee", "manager", "hr", "payroll_admin", "auditor")

SECTION_6_MATRIX: dict[Permission, dict[str, bool]] = {
    Permission.SELF_VIEW:      {"employee": True, "manager": True, "hr": True, "payroll_admin": True, "auditor": False},
    Permission.SELF_SUBMIT:    {"employee": True, "manager": True, "hr": True, "payroll_admin": True, "auditor": False},
    Permission.LEAVE_APPROVE:  {"employee": False, "manager": True, "hr": True, "payroll_admin": True, "auditor": False},
    Permission.SICK_NOTE_VIEW: {"employee": False, "manager": False, "hr": True, "payroll_admin": True, "auditor": False},
    Permission.ATTENDANCE_ADJUST: {"employee": False, "manager": True, "hr": True, "payroll_admin": True, "auditor": False},
    Permission.ATTENDANCE_ADJUST_SELF: {"employee": False, "manager": False, "hr": True, "payroll_admin": True, "auditor": False},
    Permission.OVERTIME_APPROVE: {"employee": False, "manager": True, "hr": True, "payroll_admin": True, "auditor": False},
    Permission.EXCEPTION_RESOLVE: {"employee": False, "manager": True, "hr": True, "payroll_admin": True, "auditor": False},
    Permission.ADVANCE_DECIDE: {"employee": False, "manager": False, "hr": True, "payroll_admin": True, "auditor": False},
    Permission.GRIEVANCE_HANDLE: {"employee": False, "manager": False, "hr": True, "payroll_admin": False, "auditor": False},
    Permission.PAY_RATE_REQUEST: {"employee": False, "manager": False, "hr": True, "payroll_admin": False, "auditor": False},
    Permission.PAY_RATE_APPROVE: {"employee": False, "manager": False, "hr": False, "payroll_admin": True, "auditor": False},
    Permission.PAY_RATE_VIEW: {"employee": False, "manager": False, "hr": True, "payroll_admin": True, "auditor": True},
    Permission.BANK_DETAIL_REQUEST: {"employee": False, "manager": False, "hr": True, "payroll_admin": False, "auditor": False},
    Permission.BANK_DETAIL_APPROVE: {"employee": False, "manager": False, "hr": False, "payroll_admin": True, "auditor": False},
    Permission.SHIFT_CONFIGURE: {"employee": False, "manager": False, "hr": False, "payroll_admin": True, "auditor": False},
    Permission.PAYROLL_PREVIEW: {"employee": False, "manager": False, "hr": True, "payroll_admin": True, "auditor": False},
    Permission.PAYROLL_FINALISE: {"employee": False, "manager": False, "hr": False, "payroll_admin": True, "auditor": False},
    Permission.PAYROLL_REOPEN: {"employee": False, "manager": False, "hr": False, "payroll_admin": True, "auditor": False},
    Permission.AUDIT_VIEW: {"employee": False, "manager": False, "hr": False, "payroll_admin": True, "auditor": True},
    Permission.USER_MANAGE: {"employee": False, "manager": False, "hr": False, "payroll_admin": True, "auditor": False},
    Permission.ORG_VIEW: {"employee": True, "manager": True, "hr": True, "payroll_admin": True, "auditor": True},
    Permission.ORG_MANAGE: {"employee": False, "manager": False, "hr": True, "payroll_admin": True, "auditor": False},
    Permission.ATTENDANCE_VIEW: {"employee": True, "manager": True, "hr": True, "payroll_admin": True, "auditor": False},
    Permission.INTELLIGENCE_VIEW: {"employee": False, "manager": False, "hr": True, "payroll_admin": True, "auditor": True},
    Permission.INTELLIGENCE_MANAGE: {"employee": False, "manager": False, "hr": False, "payroll_admin": True, "auditor": False},

    # --- Biometric Attendance Programme (Phase 3). Extensions, not section 6.
    # Clocking is self-service and is not the same act as adjusting another
    # person's attendance, so it is a separate permission from ATTENDANCE_ADJUST.
    Permission.ATTENDANCE_CLOCK: {"employee": True, "manager": True, "hr": True, "payroll_admin": True, "auditor": False},
    # Enrolment and device custody both touch special personal information or
    # security credentials; restricted to the two administrative roles.
    Permission.BIOMETRIC_ENROL: {"employee": False, "manager": False, "hr": True, "payroll_admin": True, "auditor": False},
    Permission.DEVICE_MANAGE: {"employee": False, "manager": False, "hr": True, "payroll_admin": True, "auditor": False},
}


def _user_with_role(role: str):
    return SimpleNamespace(role=role, id=uuid.uuid4(), employee_id=None)


_MATRIX_CASES = [
    (permission, role, expected)
    for permission, roles in SECTION_6_MATRIX.items()
    for role, expected in roles.items()
]


@pytest.mark.parametrize(
    "permission,role,expected",
    _MATRIX_CASES,
    ids=[f"{p.value}--{r}" for p, r, _ in _MATRIX_CASES],
)
def test_section_6_matrix(permission: Permission, role: str, expected: bool) -> None:
    user = _user_with_role(role)
    actual = check_permission(user, permission)
    assert actual == expected, (
        f"Permission {permission.value} for role {role}: "
        f"matrix says {expected}, code says {actual}"
    )


def test_matrix_covers_every_role() -> None:
    for permission, roles in SECTION_6_MATRIX.items():
        assert set(roles.keys()) == set(ALL_ROLES)


def test_unknown_role_has_no_permissions() -> None:
    user = _user_with_role("intruder")
    for permission in Permission:
        assert check_permission(user, permission) is False


def test_pay_rate_request_and_approve_are_disjoint() -> None:
    for role, perms in ROLE_PERMISSIONS.items():
        assert not (
            Permission.PAY_RATE_REQUEST in perms
            and Permission.PAY_RATE_APPROVE in perms
        )


def test_bank_detail_request_and_approve_are_disjoint() -> None:
    for role, perms in ROLE_PERMISSIONS.items():
        assert not (
            Permission.BANK_DETAIL_REQUEST in perms
            and Permission.BANK_DETAIL_APPROVE in perms
        )


def test_attendance_adjust_self_grants_only_hr_and_payroll_admin() -> None:
    """A3: only the two roles that already adjust others' attendance may
    self-adjust. Manager and employee remain blocked; auditor has no
    attendance-adjust capability at all.
    """
    for role in ("hr", "payroll_admin"):
        assert Permission.ATTENDANCE_ADJUST_SELF in ROLE_PERMISSIONS[role]
    for role in ("employee", "manager", "auditor"):
        assert Permission.ATTENDANCE_ADJUST_SELF not in ROLE_PERMISSIONS[role]


def test_attendance_adjust_self_requires_attendance_adjust() -> None:
    """A3: ATTENDANCE_ADJUST_SELF is an extension of ATTENDANCE_ADJUST, not
    an independent permission. A role must never hold the self variant
    without the base adjust capability."""
    for role, perms in ROLE_PERMISSIONS.items():
        if Permission.ATTENDANCE_ADJUST_SELF in perms:
            assert Permission.ATTENDANCE_ADJUST in perms, (
                f"{role} holds ATTENDANCE_ADJUST_SELF without ATTENDANCE_ADJUST"
            )


# ---------------------------------------------------------------------------
# Biometric Attendance Programme permissions
# ---------------------------------------------------------------------------


def test_attendance_clock_grants_every_employee_role_but_not_auditor() -> None:
    """Clocking is self-service, so every role that is an employee of the
    tenant may clock. The auditor may not, for exactly the reason they have
    no SELF_VIEW: an auditor is not an employee of the company they audit.
    """
    for role in ("employee", "manager", "hr", "payroll_admin"):
        assert Permission.ATTENDANCE_CLOCK in ROLE_PERMISSIONS[role], role
    assert Permission.ATTENDANCE_CLOCK not in ROLE_PERMISSIONS["auditor"]


def test_attendance_clock_does_not_imply_attendance_adjust() -> None:
    """Clocking your own time must never be a path to correcting it.

    employee holds ATTENDANCE_CLOCK and must not hold ATTENDANCE_ADJUST.
    If this ever fails, a plain employee has gained the ability to rewrite
    attendance -- which is the single most dangerous regression possible in
    this permission set.
    """
    assert Permission.ATTENDANCE_CLOCK in ROLE_PERMISSIONS["employee"]
    assert Permission.ATTENDANCE_ADJUST not in ROLE_PERMISSIONS["employee"]


def test_biometric_enrol_is_administrative_only() -> None:
    """Enrolment requires a second party to confirm the biometric belongs to
    the employee, so self-enrolment is never granted."""
    for role in ("hr", "payroll_admin"):
        assert Permission.BIOMETRIC_ENROL in ROLE_PERMISSIONS[role], role
    for role in ("employee", "manager", "auditor"):
        assert Permission.BIOMETRIC_ENROL not in ROLE_PERMISSIONS[role], role


def test_device_manage_is_administrative_only() -> None:
    for role in ("hr", "payroll_admin"):
        assert Permission.DEVICE_MANAGE in ROLE_PERMISSIONS[role], role
    for role in ("employee", "manager", "auditor"):
        assert Permission.DEVICE_MANAGE not in ROLE_PERMISSIONS[role], role


def test_biometric_permissions_never_reach_the_auditor() -> None:
    """Privacy: the auditor is excluded from attendance view already, and
    must not gain a side door via enrolment or device administration."""
    for permission in (
        Permission.ATTENDANCE_CLOCK,
        Permission.BIOMETRIC_ENROL,
        Permission.DEVICE_MANAGE,
    ):
        assert permission not in ROLE_PERMISSIONS["auditor"], permission.value


# ---------------------------------------------------------------------------
# Scope tests
# ---------------------------------------------------------------------------


def _make_employee(
    session,
    *,
    code: str,
    manager_id=None,
    site_id=None,
    branch_id=None,
    department_id=None,
):
    from datetime import date

    from app.db.tenant.models.people import Employee

    emp = Employee(
        employee_code=code,
        first_name="E",
        last_name=code,
        hire_date=date(2024, 1, 1),
        manager_id=manager_id,
        site_id=site_id,
        branch_id=branch_id,
        department_id=department_id,
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
    )
    session.add(emp)
    session.flush()
    return emp


def _make_user(session, *, username: str, role: str, employee_id=None):
    from app.db.tenant.models.people import User

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


def _employee_snapshot(role: str, employee_id=None, user_id=None):
    return SimpleNamespace(role=role, id=user_id or uuid.uuid4(), employee_id=employee_id)


@pytest.fixture()
def scope_session(disposable_tenant):
    from app.db.tenant.session import get_tenant_engine
    from sqlalchemy.orm import Session

    t = disposable_tenant
    engine = get_tenant_engine(t.tenant_db_name)
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()


def test_employee_scope_only_own(scope_session) -> None:
    me = _make_employee(scope_session, code="E1")
    other = _make_employee(scope_session, code="E2")
    scope_session.commit()
    user = _employee_snapshot("employee", employee_id=me.id)
    assert_in_scope(user, me.id, scope_session)
    with pytest.raises(ScopeViolation):
        assert_in_scope(user, other.id, scope_session)


def test_manager_with_nothing_sees_nobody(scope_session) -> None:
    target = _make_employee(scope_session, code="TGT")
    mgr_emp = _make_employee(scope_session, code="MGR-EMP")
    _make_user(scope_session, username="mgr-empty", role="manager", employee_id=mgr_emp.id)
    scope_session.commit()

    user = _employee_snapshot("manager", employee_id=mgr_emp.id)
    with pytest.raises(ScopeViolation):
        assert_in_scope(user, target.id, scope_session)


def test_manager_sees_direct_reports(scope_session) -> None:
    mgr_emp = _make_employee(scope_session, code="MGR2")
    report = _make_employee(scope_session, code="REP", manager_id=mgr_emp.id)
    other = _make_employee(scope_session, code="OTHER")
    scope_session.commit()

    user = _employee_snapshot("manager", employee_id=mgr_emp.id)
    assert_in_scope(user, report.id, scope_session)
    with pytest.raises(ScopeViolation):
        assert_in_scope(user, other.id, scope_session)


def test_manager_sees_site_scope(scope_session) -> None:
    from app.db.tenant.models.organisation import Branch, Site
    from app.db.tenant.models.people import UserScope

    mgr_emp = _make_employee(scope_session, code="MGR3")
    branch = Branch(name="B1", code=f"B-{uuid.uuid4().hex[:6]}")
    scope_session.add(branch)
    scope_session.flush()
    site = Site(branch_id=branch.id, name="S1", code=f"S-{uuid.uuid4().hex[:6]}")
    scope_session.add(site)
    scope_session.flush()
    in_site = _make_employee(scope_session, code="INSITE", site_id=site.id)
    out_of_site = _make_employee(scope_session, code="OUTSITE")

    mgr_user = _make_user(scope_session, username="mgr3", role="manager", employee_id=mgr_emp.id)
    scope_session.add(UserScope(user_id=mgr_user.id, scope_type="site", scope_id=site.id))
    scope_session.commit()

    user = _employee_snapshot("manager", employee_id=mgr_emp.id, user_id=mgr_user.id)
    assert_in_scope(user, in_site.id, scope_session)
    with pytest.raises(ScopeViolation):
        assert_in_scope(user, out_of_site.id, scope_session)


def test_manager_cannot_fetch_out_of_scope_by_uuid(scope_session) -> None:
    mgr_emp = _make_employee(scope_session, code="MGR-IDOR")
    _make_user(scope_session, username="mgr-idor", role="manager", employee_id=mgr_emp.id)
    stranger = _make_employee(scope_session, code="STRANGER")
    scope_session.commit()

    user = _employee_snapshot("manager", employee_id=mgr_emp.id)
    with pytest.raises(ScopeViolation):
        assert_in_scope(user, stranger.id, scope_session)


def test_hr_without_scopes_is_company_wide(scope_session) -> None:
    hr_emp = _make_employee(scope_session, code="HR1")
    some = _make_employee(scope_session, code="SOME")
    scope_session.commit()
    user = _employee_snapshot("hr", employee_id=hr_emp.id)
    assert_in_scope(user, some.id, scope_session)


def test_hr_with_scopes_is_restricted(scope_session) -> None:
    from app.db.tenant.models.organisation import Branch
    from app.db.tenant.models.people import UserScope

    hr_emp = _make_employee(scope_session, code="HR2")
    branch = Branch(name="HB", code=f"HB-{uuid.uuid4().hex[:6]}")
    scope_session.add(branch)
    scope_session.flush()
    inside = _make_employee(scope_session, code="HIN", branch_id=branch.id)
    outside = _make_employee(scope_session, code="HOUT")

    hr_user = _make_user(scope_session, username="hr2", role="hr", employee_id=hr_emp.id)
    scope_session.add(UserScope(user_id=hr_user.id, scope_type="branch", scope_id=branch.id))
    scope_session.commit()

    user = _employee_snapshot("hr", employee_id=hr_emp.id, user_id=hr_user.id)
    assert_in_scope(user, inside.id, scope_session)
    with pytest.raises(ScopeViolation):
        assert_in_scope(user, outside.id, scope_session)


def test_payroll_admin_and_auditor_are_company_wide(scope_session) -> None:
    admin_emp = _make_employee(scope_session, code="ADM")
    target = _make_employee(scope_session, code="ANYWHERE")
    scope_session.commit()
    for role in ("payroll_admin", "auditor"):
        user = _employee_snapshot(role, employee_id=admin_emp.id)
        assert_in_scope(user, target.id, scope_session)


def test_unknown_role_fails_closed(scope_session) -> None:
    target = _make_employee(scope_session, code="ANY")
    scope_session.commit()
    user = _employee_snapshot("intruder", employee_id=None)
    with pytest.raises(ScopeViolation):
        assert_in_scope(user, target.id, scope_session)


# ---------------------------------------------------------------------------
# Route inventory safety net
# ---------------------------------------------------------------------------

_ALLOW_LIST: frozenset[str] = frozenset({
    "/api/v1/health",
    "/api/v1/ping",
    "/api/v1/register",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/api/v1/auth/change-password",
    "/openapi.json",
    "/api/openapi.json",
    "/api/docs",
    "/api/docs/oauth2-redirect",
})


def test_every_route_has_an_auth_dependency_or_is_allow_listed() -> None:
    offenders: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if path in _ALLOW_LIST:
            continue
        has_dep = bool(getattr(route, "dependant", None) and route.dependant.dependencies)
        if not has_dep:
            offenders.append(f"{route.methods} {path}")
    assert not offenders, (
        "Routes without any Depends() dependency and not in the allow-list:\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Endpoint permission wiring (2C-5e).
#
# SECTION_6_MATRIX above tests check_permission() in isolation. These tests
# check that each HTTP endpoint is wired to the right Permission. A 403 means
# "permission explicitly denied". Scope violations are 404 in this codebase,
# so allowed roles may legitimately see 404 for single-row endpoints - but
# never 403.
# ---------------------------------------------------------------------------


def _mk_loginable_user(session, *, username, role, password):
    from datetime import date
    from app.core.security import hash_password
    from app.core.usernames import normalise_username
    from app.db.tenant.models.people import Employee, User

    employee_id = None
    if role == "employee":
        emp = Employee(
            employee_code=f"PE-{uuid.uuid4().hex[:8]}",
            first_name="E", last_name=username,
            hire_date=date(2024, 1, 1), status="active",
            employee_type="hourly", pay_basis="hourly", pay_frequency="monthly",
        )
        session.add(emp); session.flush()
        employee_id = emp.id
    user = User(
        username=normalise_username(username),
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        must_change_password=False,
        employee_id=employee_id,
        row_version=1,
    )
    session.add(user); session.commit()
    return user


def _login_for_perm(client, slug, username, password):
    r = client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": slug},
        json={"identifier": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


_ENDPOINT_CASES = [
    # (id, method, path, base_kwargs, permission)
    ("sheet", "GET", "/api/v1/attendance/sheet",
     {"params": {"from_date": "2024-05-01", "to_date": "2024-05-01"}},
     Permission.ATTENDANCE_VIEW),
    ("daily", "GET", "/api/v1/attendance/daily",
     {"params": {"date": "2024-05-01"}},
     Permission.ATTENDANCE_VIEW),
    ("mark_reviewed", "POST", "/api/v1/attendance/mark_reviewed",
     {"body": {"from_date": "2024-05-01", "to_date": "2024-05-01"}},
     Permission.ATTENDANCE_ADJUST),
]


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.parametrize(
    "case_id,method,path,base_kwargs,permission",
    _ENDPOINT_CASES,
    ids=[c[0] for c in _ENDPOINT_CASES],
)
def test_endpoint_enforces_section_6_permission(
    api_client, disposable_tenant, role, case_id, method, path, base_kwargs, permission
):
    from datetime import date as _date
    from app.db.tenant.models.people import Employee as _Emp
    from app.db.tenant.session import get_tenant_engine as _gte
    from sqlalchemy.orm import Session as _S

    engine = _gte(disposable_tenant.tenant_db_name)
    s = _S(engine)
    try:
        username = f"ep-{role[:3]}-{uuid.uuid4().hex[:8]}"
        password = "EpTest12345678!"
        _mk_loginable_user(s, username=username, role=role, password=password)

        kwargs = dict(base_kwargs)
        if "body" in base_kwargs:
            target = _Emp(
                employee_code=f"TGT-{uuid.uuid4().hex[:8]}",
                first_name="T", last_name="Target",
                hire_date=_date(2024, 1, 1), status="active",
                employee_type="hourly", pay_basis="hourly", pay_frequency="monthly",
            )
            s.add(target); s.flush()
            target_id = target.id
            s.commit()
            kwargs["json"] = {**base_kwargs["body"], "employee_ids": [str(target_id)]}
            del kwargs["body"]
    finally:
        s.close()

    tok = _login_for_perm(api_client, disposable_tenant.slug, username, password)
    headers = {"Authorization": f"Bearer {tok}", "X-Tenant-Slug": disposable_tenant.slug}

    if method.upper() == "GET":
        r = api_client.get(path, headers=headers, **kwargs)
    else:
        r = api_client.post(path, headers=headers, **kwargs)

    expected_allowed = SECTION_6_MATRIX[permission][role]
    if expected_allowed:
        assert r.status_code != 403, (
            f"{role} has {permission.value} in section 6 but {method} {path} returned 403. "
            f"Body: {r.text}"
        )
    else:
        assert r.status_code == 403, (
            f"{role} lacks {permission.value} in section 6 but {method} {path} returned "
            f"{r.status_code}, not 403. Body: {r.text}"
        )

# END OF FILE