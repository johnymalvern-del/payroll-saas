"""Biometric consent endpoint tests.

Consent is ordinary personal data, so none of this requires the approval gate.
What these tests pin:

  * consent is recorded once and a second grant is refused rather than
    silently superseding
  * withdrawal sets withdrawn_at and never deletes the row, because policy
    section 2 needs the revocation to be auditable
  * withdrawal revokes a live enrolment
  * the enrolment endpoint always refuses while the gate is closed

Endpoints are called directly rather than over HTTP. The logic under test is
the consent state machine, and building an authenticated HTTP client would test
the auth layer instead. require_permission is a Depends wrapper that only runs
through HTTP, so a direct call bypasses it, which is what these tests want.

The `user` fixture inserts a real User row rather than a stub. biometric_consent
has a foreign key from captured_by to user.id, so a fabricated actor cannot be
recorded -- correctly, since consent must name who captured it. An earlier
version of this file used a SimpleNamespace and every write failed with
ForeignKeyViolation. The fix belongs in the fixture, not in the schema: making
captured_by nullable to accommodate a fake user would remove the audit
requirement that makes the column worth having.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.biometric_consent import (
    create_enrolment,
    get_consent_status,
    grant_consent,
    withdraw_consent,
)
from app.api.v1.biometric_consent_schemas import ConsentGrantIn, WithdrawIn
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.tenant.models.people import (
    BiometricConsent,
    BiometricEnrolment,
    Employee,
    User,
)
from app.db.tenant.models.platform import AuditLog
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

    slug = f"consent-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Consent Test Co",
        admin_username="admin",
        admin_password_hash=hash_password("TestPassword123!"),
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
            row = session.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if row is not None:
                session.delete(row)


@pytest.fixture()
def db(disposable_tenant):
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    s = Session(engine)
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture()
def user(db):
    """A real User row, because captured_by and withdrawn_by are FKs to user.id.

    password_hash is a placeholder: nothing in these tests authenticates, and
    the value only has to satisfy NOT NULL. Same approach as conftest's shared
    admin user.
    """
    u = User(
        username=f"hr-{uuid.uuid4().hex[:8]}",
        password_hash="x",
        role="hr",
        is_active=True,
        must_change_password=False,
    )
    db.add(u)
    db.commit()
    return u


@pytest.fixture()
def employee(db):
    emp = Employee(
        employee_code=f"E-{uuid.uuid4().hex[:6]}",
        first_name="A",
        last_name="L",
        hire_date=date(2024, 1, 1),
        status="active",
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        row_version=1,
    )
    db.add(emp)
    db.commit()
    return emp


def _grant(db, employee, user, version="v1", method="digital"):
    return grant_consent(
        employee_id=employee.id,
        payload=ConsentGrantIn(consent_text_version=version, method=method),
        db=db,
        user=user,
    )


# ---------------------------------------------------------------------------
# Grant
# ---------------------------------------------------------------------------


def test_grant_creates_active_consent(db, employee, user):
    out = _grant(db, employee, user)

    assert out.employee_id == employee.id
    assert out.consent_text_version == "v1"
    assert out.method == "digital"
    assert out.withdrawn_at is None
    assert out.captured_by == user.id


def test_grant_is_refused_when_consent_already_active(db, employee, user):
    _grant(db, employee, user)

    with pytest.raises(AppError) as exc:
        _grant(db, employee, user, version="v2")
    assert exc.value.code == "consent_already_active"
    assert exc.value.status_code == 409

    # The first consent is untouched -- a refused grant must not supersede.
    count = db.scalar(
        select(func.count())
        .select_from(BiometricConsent)
        .where(BiometricConsent.employee_id == employee.id)
    )
    assert count == 1


def test_grant_for_unknown_employee_is_404(db, user):
    with pytest.raises(AppError) as exc:
        grant_consent(
            employee_id=uuid.uuid4(),
            payload=ConsentGrantIn(consent_text_version="v1"),
            db=db,
            user=user,
        )
    assert exc.value.status_code == 404


def test_grant_writes_an_audit_row(db, employee, user):
    out = _grant(db, employee, user)

    rows = list(
        db.scalars(
            select(AuditLog).where(AuditLog.action == "biometric_consent.granted")
        ).all()
    )
    assert len(rows) == 1
    assert rows[0].entity_id == str(out.id)
    assert rows[0].new_value["consent_text_version"] == "v1"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def test_status_reports_no_consent(db, employee, user):
    out = get_consent_status(employee_id=employee.id, db=db, user=user)

    assert out.has_consent is False
    assert out.consent is None
    assert out.enrolment is None
    assert out.biometric_active is False
    assert out.unavailable_reason == "no_consent"


def test_status_reports_consent_without_enrolment(db, employee, user):
    _grant(db, employee, user)

    out = get_consent_status(employee_id=employee.id, db=db, user=user)

    assert out.has_consent is True
    assert out.consent is not None
    assert out.enrolment is None
    # Consent alone authorises nothing.
    assert out.biometric_active is False
    assert out.unavailable_reason == "no_enrolment"


def test_status_reports_active_biometrics_when_both_exist(db, employee, user):
    """has_consent and enrolment together, tied to each other, is the only
    state in which biometrics may be used."""
    granted = _grant(db, employee, user)
    db.add(
        BiometricEnrolment(
            employee_id=employee.id,
            method="face",
            template_encrypted="ciphertext-placeholder",
            vendor="test",
            template_version="v1",
            consent_id=granted.id,
        )
    )
    db.commit()

    out = get_consent_status(employee_id=employee.id, db=db, user=user)

    assert out.has_consent is True
    assert out.enrolment is not None
    assert out.biometric_active is True
    assert out.unavailable_reason is None


# ---------------------------------------------------------------------------
# Withdrawal
# ---------------------------------------------------------------------------


def test_withdraw_sets_withdrawn_at_and_keeps_the_row(db, employee, user):
    granted = _grant(db, employee, user)

    out = withdraw_consent(
        employee_id=employee.id,
        payload=WithdrawIn(reason="changed my mind"),
        db=db,
        user=user,
    )

    assert out.withdrawn_at is not None
    assert out.withdrawn_by == user.id

    # Retained, not deleted: policy section 2 needs the revocation auditable.
    db.expire_all()
    row = db.get(BiometricConsent, granted.id)
    assert row is not None
    assert row.withdrawn_at is not None


def test_withdraw_without_active_consent_is_409(db, employee, user):
    with pytest.raises(AppError) as exc:
        withdraw_consent(
            employee_id=employee.id, payload=WithdrawIn(), db=db, user=user
        )
    assert exc.value.code == "no_active_consent"
    assert exc.value.status_code == 409


def test_withdraw_revokes_live_enrolment(db, employee, user):
    """An enrolment cannot outlive the consent it depends on."""
    granted = _grant(db, employee, user)
    enrolment = BiometricEnrolment(
        employee_id=employee.id,
        method="face",
        template_encrypted="ciphertext-placeholder",
        vendor="test",
        template_version="v1",
        consent_id=granted.id,
    )
    db.add(enrolment)
    db.commit()

    withdraw_consent(
        employee_id=employee.id, payload=WithdrawIn(), db=db, user=user
    )

    db.expire_all()
    row = db.get(BiometricEnrolment, enrolment.id)
    assert row is not None
    assert row.revoked_at is not None


def test_withdraw_writes_an_audit_row_naming_the_enrolment(db, employee, user):
    granted = _grant(db, employee, user)
    enrolment = BiometricEnrolment(
        employee_id=employee.id,
        method="face",
        template_encrypted="ciphertext-placeholder",
        vendor="test",
        template_version="v1",
        consent_id=granted.id,
    )
    db.add(enrolment)
    db.commit()

    withdraw_consent(
        employee_id=employee.id,
        payload=WithdrawIn(reason="left the company"),
        db=db,
        user=user,
    )

    row = db.scalar(
        select(AuditLog).where(AuditLog.action == "biometric_consent.withdrawn")
    )
    assert row is not None
    assert row.new_value["enrolment_revoked"] is True
    assert row.new_value["enrolment_id"] == str(enrolment.id)
    assert row.new_value["reason"] == "left the company"


def test_consent_can_be_granted_again_after_withdrawal(db, employee, user):
    _grant(db, employee, user)
    withdraw_consent(
        employee_id=employee.id, payload=WithdrawIn(), db=db, user=user
    )

    second = _grant(db, employee, user, version="v2")
    assert second.withdrawn_at is None

    # Both rows survive: the history is the point.
    count = db.scalar(
        select(func.count())
        .select_from(BiometricConsent)
        .where(BiometricConsent.employee_id == employee.id)
    )
    assert count == 2


# ---------------------------------------------------------------------------
# The approval gate
# ---------------------------------------------------------------------------


def test_enrolment_endpoint_always_refuses(db, employee, user):
    """Section 8 blocks enrolment until a signed approval record exists.

    This is the code-level enforcement point. If it ever starts succeeding,
    either the approval record was signed and this test should be rewritten
    deliberately, or the gate has been removed by accident.
    """
    _grant(db, employee, user)

    with pytest.raises(AppError) as exc:
        create_enrolment(employee_id=employee.id, db=db, user=user)

    assert exc.value.code == "biometric_not_approved"
    assert exc.value.status_code == 403

# END OF FILE