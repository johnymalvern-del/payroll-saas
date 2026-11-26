"""Biometric verification at punch time.

Two halves:

  * verify_biometric_punch -- the five verdicts, unit-level, against a stored
    enrolment and a real encryption key
  * the punch endpoint -- that a verdict reaches the punch row and, crucially,
    that NO verdict rejects a punch

The integration tests take the tenant's encryption key from
load_tenant_context rather than generating one. The punch endpoint resolves its
own crypto from the control database, so a template encrypted with a different
key would fail to decrypt and every test would report UNAVAILABLE -- passing
the "never rejects" assertions while verifying nothing. That is exactly the
vacuous pass this file has to avoid.

Probe and reference are deliberately identical in the match cases: FakeProvider
compares bytes, so equality is the only way to produce a match, and pretending
otherwise would be a fake that looks like working biometrics.
"""
from __future__ import annotations

import base64
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.biometric_consent import KEY_VERSION
from app.api.v1.device_auth import hash_device_key
from app.core.crypto import TenantCrypto
from app.core.errors import AppError
from app.core.security import hash_password
from app.core.tenant_routing import load_tenant_context
from app.core.template_crypto import TemplateCrypto
from app.db.tenant.models.attendance import CountryCalendar, ExceptionItem, Punch
from app.db.tenant.models.devices import Device
from app.db.tenant.models.organisation import Branch, Site
from app.db.tenant.models.people import BiometricConsent, BiometricEnrolment, Employee
from app.db.tenant.session import get_tenant_engine
from app.services.biometric_provider import (
    FakeProvider,
    NullProvider,
    reset_provider,
    set_provider,
)
from app.services.biometric_verify import (
    BiometricVerdict,
    ProbeInvalid,
    decode_probe_template,
    is_biometric_method,
    verify_biometric_punch,
)

REFERENCE = bytes(range(256)) + b"enrolled-minutiae"
DIFFERENT = bytes(range(256))[::-1] + b"someone-else"


@dataclass
class _Tenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def tenant() -> Iterator[_Tenant]:
    from app.db.control.models import Subscriber
    from app.db.control.session import control_session
    from app.services.provisioning import (
        _drop_tenant_database,
        _tenant_db_name,
        provision_tenant,
    )

    slug = f"biover-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Verify Test Co",
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
def crypto(tenant) -> TenantCrypto:
    """The key the punch endpoint will actually use.

    Not a generated key: the endpoint resolves its own from the control
    database, so anything else encrypts templates it cannot read.
    """
    return load_tenant_context(tenant.slug).crypto


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


@pytest.fixture(autouse=True)
def _reset():
    yield
    reset_provider()


def _enrol(
    db,
    crypto,
    employee,
    consent,
    *,
    template: bytes = REFERENCE,
    version: str = "fake-v1",
    revoked: bool = False,
    method: str = "fingerprint",
) -> BiometricEnrolment:
    stored = TemplateCrypto(crypto, key_version=KEY_VERSION).encrypt_template(template)
    row = BiometricEnrolment(
        employee_id=employee.id,
        method=method,
        template_encrypted=stored,
        vendor="fake",
        template_version=version,
        consent_id=consent.id,
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def test_matched_when_probe_equals_reference(db, crypto, employee, consent):
    set_provider(FakeProvider())
    _enrol(db, crypto, employee, consent)

    r = verify_biometric_punch(
        db,
        employee_id=employee.id,
        biometric_type="fingerprint",
        probe_raw=REFERENCE,
        crypto=crypto,
    )

    assert r.verdict is BiometricVerdict.MATCHED
    assert r.verified is True
    assert r.flags == []


def test_below_threshold_when_probe_differs(db, crypto, employee, consent):
    set_provider(FakeProvider())
    _enrol(db, crypto, employee, consent)

    r = verify_biometric_punch(
        db,
        employee_id=employee.id,
        biometric_type="fingerprint",
        probe_raw=DIFFERENT,
        crypto=crypto,
    )

    assert r.verdict is BiometricVerdict.BELOW_THRESHOLD
    assert r.verified is False
    assert "match_below_threshold" in r.flags


def test_not_enrolled_when_no_enrolment_exists(db, crypto, employee, consent):
    set_provider(FakeProvider())

    r = verify_biometric_punch(
        db,
        employee_id=employee.id,
        biometric_type="fingerprint",
        probe_raw=REFERENCE,
        crypto=crypto,
    )

    assert r.verdict is BiometricVerdict.NOT_ENROLLED
    assert "biometric_not_enrolled" in r.flags


def test_revoked_enrolment_is_not_used(db, crypto, employee, consent):
    set_provider(FakeProvider())
    _enrol(db, crypto, employee, consent, revoked=True)

    r = verify_biometric_punch(
        db,
        employee_id=employee.id,
        biometric_type="fingerprint",
        probe_raw=REFERENCE,
        crypto=crypto,
    )

    assert r.verdict is BiometricVerdict.NOT_ENROLLED


def test_consent_missing_when_withdrawn_but_enrolment_still_live(
    db, crypto, employee, consent
):
    """Withdrawal revokes the enrolment row. If the two diverge, refuse anyway.

    A withdrawal that failed halfway leaves exactly this state, and the
    template must not be used on the strength of a stale row.
    """
    set_provider(FakeProvider())
    _enrol(db, crypto, employee, consent)

    consent.withdrawn_at = datetime.now(timezone.utc)
    db.commit()

    r = verify_biometric_punch(
        db,
        employee_id=employee.id,
        biometric_type="fingerprint",
        probe_raw=REFERENCE,
        crypto=crypto,
    )

    assert r.verdict is BiometricVerdict.CONSENT_MISSING
    assert "biometric_consent_missing" in r.flags


def test_config_mismatch_when_template_version_differs(db, crypto, employee, consent):
    set_provider(FakeProvider(template_version="fake-v2"))
    _enrol(db, crypto, employee, consent, version="fake-v1")

    r = verify_biometric_punch(
        db,
        employee_id=employee.id,
        biometric_type="fingerprint",
        probe_raw=REFERENCE,
        crypto=crypto,
    )

    assert r.verdict is BiometricVerdict.CONFIG_MISMATCH
    assert "biometric_template_mismatch" in r.flags


def test_unavailable_when_stored_template_cannot_be_decrypted(
    db, crypto, employee, consent
):
    from cryptography.fernet import Fernet

    set_provider(FakeProvider())
    _enrol(db, crypto, employee, consent)

    # A different key: the stored ciphertext is intact but unreadable. This is a
    # system fault, not a failed match, and reporting it as a mismatch would
    # accuse an employee over a key rotation.
    r = verify_biometric_punch(
        db,
        employee_id=employee.id,
        biometric_type="fingerprint",
        probe_raw=REFERENCE,
        crypto=TenantCrypto(Fernet.generate_key()),
    )

    assert r.verdict is BiometricVerdict.UNAVAILABLE
    assert "biometric_verification_unavailable" in r.flags


def test_unavailable_when_no_provider_configured(db, crypto, employee, consent):
    reset_provider()
    assert isinstance(NullProvider(), NullProvider)
    _enrol(db, crypto, employee, consent)

    r = verify_biometric_punch(
        db,
        employee_id=employee.id,
        biometric_type="fingerprint",
        probe_raw=REFERENCE,
        crypto=crypto,
    )

    assert r.verdict in (
        BiometricVerdict.UNAVAILABLE,
        BiometricVerdict.CONFIG_MISMATCH,
    )


def test_score_is_quantised_to_two_places(db, crypto, employee, consent):
    set_provider(FakeProvider(match_score=87.456))
    _enrol(db, crypto, employee, consent)

    r = verify_biometric_punch(
        db,
        employee_id=employee.id,
        biometric_type="fingerprint",
        probe_raw=REFERENCE,
        crypto=crypto,
    )

    assert str(r.score) == "87.46"


def test_custom_threshold_is_honoured(db, crypto, employee, consent):
    set_provider(FakeProvider(match_score=55.0))
    _enrol(db, crypto, employee, consent)

    passing = verify_biometric_punch(
        db,
        employee_id=employee.id,
        biometric_type="fingerprint",
        probe_raw=REFERENCE,
        crypto=crypto,
        threshold=50.0,
    )
    failing = verify_biometric_punch(
        db,
        employee_id=employee.id,
        biometric_type="fingerprint",
        probe_raw=REFERENCE,
        crypto=crypto,
        threshold=60.0,
    )

    assert passing.verdict is BiometricVerdict.MATCHED
    assert failing.verdict is BiometricVerdict.BELOW_THRESHOLD


# ---------------------------------------------------------------------------
# Probe decoding
# ---------------------------------------------------------------------------


def test_decode_probe_accepts_valid_base64():
    assert decode_probe_template(base64.b64encode(REFERENCE).decode()) == REFERENCE


def test_decode_probe_requires_a_value():
    with pytest.raises(ProbeInvalid):
        decode_probe_template(None)


def test_decode_probe_rejects_non_base64():
    with pytest.raises(ProbeInvalid):
        decode_probe_template("not base64 !!")


def test_decode_probe_rejects_short_payload():
    with pytest.raises(ProbeInvalid):
        decode_probe_template(base64.b64encode(b"\x00\x01").decode())


def test_decode_probe_tolerates_whitespace():
    encoded = base64.b64encode(REFERENCE).decode()
    wrapped = encoded[:20] + "\n" + encoded[20:]
    assert decode_probe_template(wrapped) == REFERENCE


def test_is_biometric_method():
    assert is_biometric_method("fingerprint") is True
    assert is_biometric_method("face") is True
    assert is_biometric_method("code") is False
    assert is_biometric_method("pin") is False


# ---------------------------------------------------------------------------
# Through the punch endpoint -- no verdict may reject
# ---------------------------------------------------------------------------


@pytest.fixture()
def punch_env(api_client, db, tenant, crypto):
    year = datetime.now(timezone.utc).year
    for y in (year, year - 1):
        db.add(
            CountryCalendar(
                country_code="ZA",
                holiday_date=date(y, 1, 1),
                name="New Year",
                source_ref="test",
            )
        )
    db.commit()

    branch = Branch(
        name=f"B-{uuid.uuid4().hex[:6]}",
        code=f"B-{uuid.uuid4().hex[:6]}",
        is_active=True,
        row_version=1,
    )
    db.add(branch)
    db.commit()
    site = Site(
        branch_id=branch.id,
        name="S",
        code=f"S-{uuid.uuid4().hex[:6]}",
        site_type="site",
        timezone="Africa/Johannesburg",
        is_active=True,
        row_version=1,
    )
    db.add(site)
    db.commit()

    raw = secrets.token_hex(32)
    db.add(
        Device(
            site_id=site.id,
            name=f"Dev-{uuid.uuid4().hex[:6]}",
            device_type="usb_fingerprint",
            api_key_hash=hash_device_key(raw),
            status="active",
            allows_code_only=False,
            require_photo_for_code=True,
            pending_punch_count=0,
            row_version=1,
        )
    )
    db.commit()

    emp = Employee(
        employee_code=f"E-{uuid.uuid4().hex[:6]}",
        first_name="A",
        last_name="L",
        hire_date=date(2024, 1, 1),
        status="active",
        site_id=site.id,
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        row_version=1,
    )
    db.add(emp)
    db.commit()

    con = BiometricConsent(
        employee_id=emp.id, consent_text_version="v1", method="digital"
    )
    db.add(con)
    db.commit()

    return api_client, tenant, raw, emp, con


def _bio_payload(employee_id, probe: bytes | None, **overrides):
    now = datetime.now(timezone.utc)
    body = {
        "client_punch_id": str(uuid.uuid4()),
        "employee_id": str(employee_id),
        "device_time": (now - timedelta(minutes=5)).isoformat(),
        "device_now_at_send": now.isoformat(),
        "method": "fingerprint",
        "raw_payload": {},
    }
    if probe is not None:
        body["probe_template_base64"] = base64.b64encode(probe).decode()
    body.update(overrides)
    return body


def _post(client, slug, key, body):
    return client.post(
        "/api/v1/punches",
        headers={"X-Tenant-Slug": slug, "X-Device-Key": key},
        json=body,
    )


def test_matching_probe_is_accepted_with_no_flag(punch_env, db, crypto):
    client, tenant, key, emp, con = punch_env
    set_provider(FakeProvider())
    _enrol(db, crypto, emp, con)

    r = _post(client, tenant.slug, key, _bio_payload(emp.id, REFERENCE))

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "accepted"
    assert body["flags"] == []


def test_below_threshold_is_low_confidence_not_rejected(punch_env, db, crypto):
    """The falsifiable claim for the whole feature."""
    client, tenant, key, emp, con = punch_env
    set_provider(FakeProvider())
    _enrol(db, crypto, emp, con)

    r = _post(client, tenant.slug, key, _bio_payload(emp.id, DIFFERENT))

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] != "rejected", (
        "a failed match must never remove the punch from pay"
    )
    assert "match_below_threshold" in body["flags"]


def test_not_enrolled_is_accepted_and_flagged(punch_env, db):
    client, tenant, key, emp, _con = punch_env
    set_provider(FakeProvider())

    r = _post(client, tenant.slug, key, _bio_payload(emp.id, REFERENCE))

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "accepted"
    assert "biometric_not_enrolled" in body["flags"]


def test_missing_probe_is_a_400_and_creates_no_punch(punch_env, db):
    client, tenant, key, emp, con = punch_env
    set_provider(FakeProvider())

    r = _post(client, tenant.slug, key, _bio_payload(emp.id, None))

    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "probe_invalid"
    assert db.scalar(select(Punch).where(Punch.employee_id == emp.id)) is None


def test_client_supplied_score_is_ignored_for_biometrics(punch_env, db, crypto):
    """A terminal reporting its own success has not been verified."""
    client, tenant, key, emp, con = punch_env
    set_provider(FakeProvider())
    _enrol(db, crypto, emp, con)

    r = _post(
        client,
        tenant.slug,
        key,
        _bio_payload(emp.id, DIFFERENT, match_score="99", liveness_passed=True),
    )

    assert r.status_code == 201, r.text
    body = r.json()
    assert "match_below_threshold" in body["flags"], (
        "the server must score the probe, not trust the device's claim"
    )


def test_biometric_exception_reaches_the_queue(punch_env, db, crypto):
    client, tenant, key, emp, con = punch_env
    set_provider(FakeProvider())
    _enrol(db, crypto, emp, con)

    r = _post(client, tenant.slug, key, _bio_payload(emp.id, DIFFERENT))
    assert r.status_code == 201, r.text

    db.expire_all()
    types = set(
        db.scalars(
            select(ExceptionItem.type).where(
                ExceptionItem.employee_id == emp.id,
                ExceptionItem.status == "open",
            )
        ).all()
    )
    assert "match_below_threshold" in types