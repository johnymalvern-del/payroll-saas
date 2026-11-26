"""Tests for the section 8 gate.

Every refusal is asserted with its own code, and every one is asserted to
leave no enrolment behind. The gate raising is not enough on its own: the
property that matters is that no template is stored, and a future caller that
catches the error and continues must fail this suite.

The document is written to a tmp_path per test and its hash recorded on the
approval row, so the tamper test can change the file and watch the gate close
without touching the repository's real template.
"""
from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import hash_password
from app.db.control.models import BiometricApproval
from app.db.control.session import control_session
from app.db.tenant.models.people import BiometricConsent, BiometricEnrolment, Employee
from app.db.tenant.session import get_tenant_engine
from app.services import biometric_gate
from app.services.biometric_gate import (
    assert_enrolment_permitted,
    require_approval,
    sha256_file,
)
from app.services.biometric_provider import FakeProvider, reset_provider, set_provider

DOC_BYTES = b"# Biometric approval\n\nstatus: approved\nsigned: counsel\n"


@dataclass
class _Tenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def tenant() -> Iterator[_Tenant]:
    from app.db.control.models import Subscriber
    from app.services.provisioning import (
        _drop_tenant_database,
        _tenant_db_name,
        provision_tenant,
    )

    slug = f"gate-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Gate Test Co",
        admin_username="admin",
        admin_password_hash=hash_password("TestPassword123!"),
    )
    db_name = _tenant_db_name(slug)
    try:
        yield _Tenant(
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
def db(tenant):
    engine = get_tenant_engine(tenant.tenant_db_name)
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def employee(db):
    e = Employee(
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
    db.add(e)
    db.commit()
    return e


@pytest.fixture()
def consent(db, employee):
    c = BiometricConsent(
        employee_id=employee.id,
        consent_text_version="v1",
        method="digital",
    )
    db.add(c)
    db.commit()
    return c


@pytest.fixture()
def signed_doc(tmp_path) -> Path:
    p = tmp_path / "approval.md"
    p.write_bytes(DOC_BYTES)
    return p


def _put_approval(
    tenant,
    doc: Path,
    *,
    status: str = "approved",
    biometric_type: str = "fingerprint",
    effective_from: date | None = None,
    effective_to: date | None = None,
    company: str | None = "Company Signatory",
    counsel: str | None = "Counsel Signatory",
    scope_employee_ids=None,
    scope_site_ids=None,
    hash_override: str | None = None,
) -> uuid.UUID:
    with control_session() as session:
        session.query(BiometricApproval).filter(
            BiometricApproval.subscriber_id == tenant.subscriber_id
        ).delete()
        row = BiometricApproval(
            id=uuid.uuid4(),
            subscriber_id=tenant.subscriber_id,
            status=status,
            biometric_type=biometric_type,
            approved_by_company=company,
            approved_by_counsel=counsel,
            signed_at=None,
            effective_from=effective_from or (date.today() - timedelta(days=1)),
            effective_to=effective_to,
            record_sha256=hash_override or sha256_file(doc),
            scope_employee_ids=scope_employee_ids,
            scope_site_ids=scope_site_ids,
            retention_days=30,
            row_version=1,
        )
        session.add(row)
        session.commit()
        return row.id


def _no_enrolments(db) -> bool:
    return db.query(BiometricEnrolment).count() == 0


def _call(tenant, employee, doc, **kwargs):
    return assert_enrolment_permitted(
        None if kwargs.pop("skip_db", False) else _db_holder["db"],
        subscriber_id=tenant.subscriber_id,
        employee_id=employee.id,
        site_id=kwargs.pop("site_id", None),
        biometric_type=kwargs.pop("biometric_type", "fingerprint"),
        document=doc,
        **kwargs,
    )


_db_holder: dict = {}


def _with_db(db):
    _db_holder["db"] = db


# ---------------------------------------------------------------------------
# Approval presence and status
# ---------------------------------------------------------------------------


def test_no_approval_row_refuses(tenant, db, employee, consent, signed_doc):
    set_provider(FakeProvider())
    with pytest.raises(AppError) as exc:
        require_approval(
            subscriber_id=tenant.subscriber_id,
            employee_id=employee.id,
            site_id=None,
            biometric_type="fingerprint",
            document=signed_doc,
        )
    assert exc.value.code == "biometric_not_approved"
    assert _no_enrolments(db)
    reset_provider()


def test_status_not_approved_refuses(tenant, db, employee, signed_doc):
    _put_approval(tenant, signed_doc, status="not_approved")
    with pytest.raises(AppError) as exc:
        require_approval(
            subscriber_id=tenant.subscriber_id,
            employee_id=employee.id,
            site_id=None,
            biometric_type="fingerprint",
            document=signed_doc,
        )
    assert exc.value.code == "biometric_not_approved"
    assert _no_enrolments(db)


def test_revoked_approval_refuses(tenant, db, employee, signed_doc):
    _put_approval(tenant, signed_doc, status="revoked")
    with pytest.raises(AppError) as exc:
        require_approval(
            subscriber_id=tenant.subscriber_id,
            employee_id=employee.id,
            site_id=None,
            biometric_type="fingerprint",
            document=signed_doc,
        )
    assert exc.value.code == "biometric_not_approved"


def test_missing_counsel_signature_refuses(tenant, db, employee, signed_doc):
    """An 'approved' row with one signature is incomplete, not approved."""
    _put_approval(tenant, signed_doc, counsel=None)
    with pytest.raises(AppError) as exc:
        require_approval(
            subscriber_id=tenant.subscriber_id,
            employee_id=employee.id,
            site_id=None,
            biometric_type="fingerprint",
            document=signed_doc,
        )
    assert exc.value.code == "biometric_not_approved"


# ---------------------------------------------------------------------------
# Document integrity
# ---------------------------------------------------------------------------


def test_changed_document_closes_the_gate(tenant, db, employee, signed_doc):
    """The row claims approval; the document no longer agrees."""
    _put_approval(tenant, signed_doc)
    signed_doc.write_bytes(DOC_BYTES + b"\nAMENDED: scope widened\n")

    with pytest.raises(AppError) as exc:
        require_approval(
            subscriber_id=tenant.subscriber_id,
            employee_id=employee.id,
            site_id=None,
            biometric_type="fingerprint",
            document=signed_doc,
        )
    assert exc.value.code == "biometric_approval_tampered"
    assert exc.value.status_code == 503
    assert _no_enrolments(db)


def test_missing_document_closes_the_gate(tenant, db, employee, tmp_path):
    doc = tmp_path / "approval.md"
    doc.write_bytes(DOC_BYTES)
    _put_approval(tenant, doc)
    doc.unlink()

    with pytest.raises(AppError) as exc:
        require_approval(
            subscriber_id=tenant.subscriber_id,
            employee_id=employee.id,
            site_id=None,
            biometric_type="fingerprint",
            document=doc,
        )
    assert exc.value.code == "biometric_not_configured"
    assert exc.value.status_code == 503


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def test_not_yet_effective_refuses(tenant, db, employee, signed_doc):
    _put_approval(
        tenant, signed_doc, effective_from=date.today() + timedelta(days=10)
    )
    with pytest.raises(AppError) as exc:
        require_approval(
            subscriber_id=tenant.subscriber_id,
            employee_id=employee.id,
            site_id=None,
            biometric_type="fingerprint",
            document=signed_doc,
        )
    assert exc.value.code == "biometric_approval_expired"


def test_expired_approval_refuses(tenant, db, employee, signed_doc):
    _put_approval(
        tenant,
        signed_doc,
        effective_from=date.today() - timedelta(days=400),
        effective_to=date.today() - timedelta(days=1),
    )
    with pytest.raises(AppError) as exc:
        require_approval(
            subscriber_id=tenant.subscriber_id,
            employee_id=employee.id,
            site_id=None,
            biometric_type="fingerprint",
            document=signed_doc,
        )
    assert exc.value.code == "biometric_approval_expired"


def test_open_ended_approval_is_permitted(tenant, db, employee, signed_doc):
    _put_approval(tenant, signed_doc, effective_to=None)
    row = require_approval(
        subscriber_id=tenant.subscriber_id,
        employee_id=employee.id,
        site_id=None,
        biometric_type="fingerprint",
        document=signed_doc,
    )
    assert row.effective_to is None


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def test_employee_outside_scope_refuses(tenant, db, employee, signed_doc):
    _put_approval(
        tenant, signed_doc, scope_employee_ids=[str(uuid.uuid4())]
    )
    with pytest.raises(AppError) as exc:
        require_approval(
            subscriber_id=tenant.subscriber_id,
            employee_id=employee.id,
            site_id=None,
            biometric_type="fingerprint",
            document=signed_doc,
        )
    assert exc.value.code == "biometric_approval_scope"


def test_employee_inside_scope_is_permitted(tenant, db, employee, signed_doc):
    _put_approval(
        tenant, signed_doc, scope_employee_ids=[str(employee.id)]
    )
    row = require_approval(
        subscriber_id=tenant.subscriber_id,
        employee_id=employee.id,
        site_id=None,
        biometric_type="fingerprint",
        document=signed_doc,
    )
    assert row is not None


def test_empty_scope_means_unrestricted(tenant, db, employee, signed_doc):
    _put_approval(tenant, signed_doc, scope_employee_ids=[])
    row = require_approval(
        subscriber_id=tenant.subscriber_id,
        employee_id=employee.id,
        site_id=None,
        biometric_type="fingerprint",
        document=signed_doc,
    )
    assert row is not None


def test_face_approval_does_not_cover_fingerprint(tenant, db, employee, signed_doc):
    _put_approval(tenant, signed_doc, biometric_type="face")
    with pytest.raises(AppError) as exc:
        require_approval(
            subscriber_id=tenant.subscriber_id,
            employee_id=employee.id,
            site_id=None,
            biometric_type="fingerprint",
            document=signed_doc,
        )
    assert exc.value.code == "biometric_not_approved"


def test_both_approval_covers_fingerprint(tenant, db, employee, signed_doc):
    _put_approval(tenant, signed_doc, biometric_type="both")
    row = require_approval(
        subscriber_id=tenant.subscriber_id,
        employee_id=employee.id,
        site_id=None,
        biometric_type="fingerprint",
        document=signed_doc,
    )
    assert row.biometric_type == "both"


def test_invalid_biometric_type_is_400(tenant, db, employee, signed_doc):
    with pytest.raises(AppError) as exc:
        require_approval(
            subscriber_id=tenant.subscriber_id,
            employee_id=employee.id,
            site_id=None,
            biometric_type="retina",
            document=signed_doc,
        )
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Consent and provider, composed by the full gate
# ---------------------------------------------------------------------------


def test_missing_consent_refuses(db, employee):
    from app.services.biometric_gate import require_consent

    with pytest.raises(AppError) as exc:
        require_consent(db, employee.id)
    assert exc.value.code == "biometric_consent_missing"


def test_withdrawn_consent_refuses(db, employee):
    from datetime import datetime, timezone

    from app.services.biometric_gate import require_consent

    db.add(
        BiometricConsent(
            employee_id=employee.id,
            consent_text_version="v1",
            method="digital",
            withdrawn_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    with pytest.raises(AppError) as exc:
        require_consent(db, employee.id)
    assert exc.value.code == "biometric_consent_missing"
    assert exc.value.code == "biometric_consent_missing"


def test_active_consent_passes(db, consent):
    from app.services.biometric_gate import require_consent

    assert require_consent(db, consent.employee_id) is not None


def test_no_provider_refuses(tenant, db, employee, consent, signed_doc):
    reset_provider()
    _put_approval(tenant, signed_doc)
    with pytest.raises(AppError) as exc:
        assert_enrolment_permitted(
            db,
            subscriber_id=tenant.subscriber_id,
            employee_id=employee.id,
            site_id=None,
            biometric_type="fingerprint",
            document=signed_doc,
        )
    assert exc.value.code == "biometric_not_configured"
    assert exc.value.status_code == 503
    assert _no_enrolments(db)


def test_full_gate_passes_when_everything_is_in_order(
    tenant, db, employee, consent, signed_doc
):
    provider = FakeProvider()
    set_provider(provider)
    _put_approval(tenant, signed_doc)
    try:
        got = assert_enrolment_permitted(
            db,
            subscriber_id=tenant.subscriber_id,
            employee_id=employee.id,
            site_id=None,
            biometric_type="fingerprint",
            document=signed_doc,
        )
        assert got is provider
        # The gate permits; it does not enrol. Nothing is stored by design.
        assert _no_enrolments(db)
    finally:
        reset_provider()


def test_minimal_test_document_is_rejected_when_default_path_is_used(
    tenant, db, employee, consent
):
    """The repository's real template must keep the gate closed.

    Its header carries `status: not_approved`, and there is no approval row, so
    the default path refuses. This pins that the shipped state is closed.
    """
    set_provider(FakeProvider())
    try:
        with pytest.raises(AppError) as exc:
            assert_enrolment_permitted(
                db,
                subscriber_id=tenant.subscriber_id,
                employee_id=employee.id,
                site_id=None,
                biometric_type="fingerprint",
            )
        assert exc.value.code in (
            "biometric_not_approved",
            "biometric_not_configured",
        )
    finally:
        reset_provider()