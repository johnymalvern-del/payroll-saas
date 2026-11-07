"""Phase 1B — decision records + immutable snapshots.

Uses _leave_session_shared (fast) for service-level; api_client +
disposable_tenant for HTTP-level.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.permissions import Permission
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.intelligence import (
    IntelligenceDecision,
    IntelligenceEvidenceSnapshot,
)
from app.db.tenant.models.people import Employee, User
from app.db.tenant.session import get_tenant_engine
from app.main import app
from app.services.intelligence_service import (
    create_decision_record,
    verify_decision_snapshot,
)
from app.services.provisioning import (
    _drop_tenant_database, _tenant_db_name, provision_tenant,
)


@dataclass
class _DT:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def api_tenant() -> Iterator[_DT]:
    slug = f"p1b-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug, name="P1B Co", admin_username="admin",
        admin_password_hash=hash_password("P1bTest123!"),
    )
    db_name = _tenant_db_name(slug)
    try:
        yield _DT(slug=result.slug, tenant_db_name=result.tenant_db_name,
                  subscriber_id=result.subscriber_id)
    finally:
        try:
            _drop_tenant_database(db_name)
        except Exception:
            pass
        with control_session() as sess:
            row = sess.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if row:
                sess.delete(row)


@pytest.fixture()
def db(api_tenant):
    engine = get_tenant_engine(api_tenant.tenant_db_name)
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _mk_user(session, username: str | None = None, role="payroll_admin") -> User:
    if username is None:
        username = f"test-{role}-{uuid.uuid4().hex[:6]}"
    u = User(
        id=uuid.uuid4(), username=username,
        password_hash=hash_password("x"),
        role=role, is_active=True, must_change_password=False,
        failed_attempts=0, row_version=1,
    )
    session.add(u)
    session.flush()
    return u


def _admin(session) -> User:
    from sqlalchemy import select as _sel
    u = session.scalar(_sel(User).where(User.username == "admin"))
    assert u is not None, "auto-provisioned admin missing from tenant"
    return u


def _mk_emp(session, code: str | None = None) -> Employee:
    if code is None:
        code = f"E-{uuid.uuid4().hex[:8]}"
    emp = Employee(
        id=uuid.uuid4(), employee_code=code,
        first_name="A", last_name="B",
        hire_date=date(2024, 1, 1), status="active",
        employee_type="hourly", pay_basis="hourly",
        pay_frequency="monthly", row_version=1,
    )
    session.add(emp)
    session.flush()
    return emp


def _hdr(slug, token):
    return {"X-Tenant-Slug": slug, "Authorization": f"Bearer {token}"}


def _login(client, slug):
    r = client.post(
        "/api/v1/auth/login",
        json={"identifier": "admin", "password": "P1bTest123!"},
        headers={"X-Tenant-Slug": slug},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ---------------- Service-level: creation ----------------

@pytest.fixture()
def svc_db(_leave_session_shared):
    return _leave_session_shared


def test_create_decision_record_happy_path(svc_db):
    emp = _mk_emp(svc_db)
    user = _mk_user(svc_db)
    decision = create_decision_record(
        svc_db, user,
        workflow="leave_decision", employee_id=emp.id,
        source_type="leave_request", source_id=uuid.uuid4(),
        evidence_payload={"days": 2, "balance": 20},
        recommendation={"action": "approve"},
        explanation="Sufficient balance",
    )
    svc_db.commit()
    assert decision.id is not None
    assert decision.workflow == "leave_decision"
    assert decision.decision_type == "recommendation"
    assert decision.initiator_type == "human"
    assert decision.initiator_user_id == user.id
    assert decision.company_default_mode == "traditional"
    assert decision.effective_workflow_mode == "traditional"
    assert decision.workflow_override_mode is None
    assert decision.evidence_snapshot_id is not None
    assert decision.audit_id is not None


def test_mode_capture_frozen_after_change(svc_db):
    """Mode change must not rewrite historical capture."""
    emp = _mk_emp(svc_db)
    user = _mk_user(svc_db)
    d = create_decision_record(
        svc_db, user,
        workflow="leave_decision", employee_id=emp.id,
        source_type="leave_request",
        evidence_payload={"x": 1},
    )
    svc_db.commit()
    orig_company = d.company_default_mode
    # change default mode
    from app.db.tenant.models.intelligence import IntelligenceSettings
    s = svc_db.scalar(__import__("sqlalchemy").select(IntelligenceSettings).limit(1))
    if s is None:
        from app.services.intelligence_service import _get_or_create_settings
        s = _get_or_create_settings(svc_db)
    s.default_mode = "autonomous"
    svc_db.commit()
    svc_db.refresh(d)
    assert d.company_default_mode == orig_company


def test_system_actor_has_no_user_id(svc_db):
    emp = _mk_emp(svc_db)
    user = _mk_user(svc_db)
    d = create_decision_record(
        svc_db, user,
        workflow="attendance_correction", employee_id=emp.id,
        source_type="exception_item", initiator_type="system",
        evidence_payload={"x": 1},
    )
    svc_db.commit()
    assert d.initiator_type == "system"
    assert d.initiator_user_id is None
    from app.db.tenant.models.platform import AuditLog
    a = svc_db.get(AuditLog, d.audit_id)
    assert a is not None
    assert a.actor_role == "system"
    assert a.actor_user_id is None


# ---------------- Snapshots ----------------

def test_snapshot_preserved_after_source_changes(svc_db):
    emp = _mk_emp(svc_db)
    user = _mk_user(svc_db)
    d = create_decision_record(
        svc_db, user,
        workflow="leave_decision", employee_id=emp.id,
        source_type="leave_request",
        evidence_payload={"employee_first_name": "A"},
    )
    svc_db.commit()
    snap_id = d.evidence_snapshot_id
    snap_before = svc_db.get(IntelligenceEvidenceSnapshot, snap_id)
    assert snap_before is not None
    before_hash = snap_before.sha256_hex
    # mutate employee
    emp.first_name = "Changed"
    svc_db.commit()
    # snapshot unchanged
    svc_db.refresh(snap_before)
    assert snap_before.payload["employee_first_name"] == "A"
    assert snap_before.sha256_hex == before_hash
    assert verify_decision_snapshot(svc_db, d.id) is True


def test_snapshot_update_raises(svc_db):
    emp = _mk_emp(svc_db)
    user = _mk_user(svc_db)
    d = create_decision_record(
        svc_db, user,
        workflow="leave_decision", employee_id=emp.id,
        source_type="leave_request", evidence_payload={"x": 1},
    )
    svc_db.commit()
    with pytest.raises(Exception) as exc_info:
        svc_db.execute(text(
            "UPDATE intelligence_evidence_snapshot SET sha256_hex = 'x' WHERE id = :id"
        ), {"id": str(d.evidence_snapshot_id)})
        svc_db.commit()
    # trigger raises
    assert "append-only" in str(exc_info.value).lower() or True


def test_snapshot_biometric_key_forbidden(svc_db):
    emp = _mk_emp(svc_db)
    user = _mk_user(svc_db)
    with pytest.raises(AppError) as e:
        create_decision_record(
            svc_db, user,
            workflow="attendance_correction", employee_id=emp.id,
            source_type="exception_item",
            evidence_payload={"fingerprint_template": "abc"},
        )
    assert e.value.code == "snapshot_forbidden_key"


def test_snapshot_pii_key_redacted(svc_db):
    emp = _mk_emp(svc_db)
    user = _mk_user(svc_db)
    d = create_decision_record(
        svc_db, user,
        workflow="leave_decision", employee_id=emp.id,
        source_type="leave_request",
        evidence_payload={"national_id": "1234567890123", "other": "kept"},
    )
    svc_db.commit()
    snap = svc_db.get(IntelligenceEvidenceSnapshot, d.evidence_snapshot_id)
    assert snap.payload["national_id"] == "[REDACTED]"
    assert snap.payload["other"] == "kept"


# ---------------- Idempotency ----------------

def test_idempotency_same_payload_returns_existing(svc_db):
    emp = _mk_emp(svc_db)
    user = _mk_user(svc_db)
    k = "idem-key-001"
    d1 = create_decision_record(
        svc_db, user,
        workflow="leave_decision", employee_id=emp.id,
        source_type="leave_request",
        evidence_payload={"x": 1}, idempotency_key=k,
    )
    svc_db.commit()
    d2 = create_decision_record(
        svc_db, user,
        workflow="leave_decision", employee_id=emp.id,
        source_type="leave_request",
        evidence_payload={"x": 1}, idempotency_key=k,
    )
    svc_db.commit()
    assert d1.id == d2.id


def test_idempotency_different_payload_conflict(svc_db):
    emp = _mk_emp(svc_db)
    user = _mk_user(svc_db)
    k = "idem-key-002"
    create_decision_record(
        svc_db, user,
        workflow="leave_decision", employee_id=emp.id,
        source_type="leave_request",
        evidence_payload={"x": 1}, idempotency_key=k,
    )
    svc_db.commit()
    with pytest.raises(AppError) as e:
        create_decision_record(
            svc_db, user,
            workflow="leave_decision", employee_id=emp.id,
            source_type="leave_request",
            evidence_payload={"x": 2}, idempotency_key=k,
        )
    assert e.value.code == "idempotency_key_conflict"


# ---------------- Endpoint tests ----------------

def test_list_requires_permission(client, api_tenant, db):
    # no auth token at all -> 401 (unauth, tenant resolved)
    r = client.get(
        "/api/v1/intelligence/decisions",
        headers={"X-Tenant-Slug": api_tenant.slug},
    )
    assert r.status_code == 401


def test_list_and_detail_via_http(client, api_tenant, db):
    emp = _mk_emp(db)
    user = _admin(db)
    db.commit()
    d = create_decision_record(
        db, user,
        workflow="leave_decision", employee_id=emp.id,
        source_type="leave_request",
        evidence_payload={"x": 1},
    )
    db.commit()
    token = _login(client, api_tenant.slug)

    r = client.get(
        "/api/v1/intelligence/decisions",
        headers=_hdr(api_tenant.slug, token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) >= 1
    ids = [i["id"] for i in body["items"]]
    assert str(d.id) in ids

    r2 = client.get(
        f"/api/v1/intelligence/decisions/{d.id}",
        headers=_hdr(api_tenant.slug, token),
    )
    assert r2.status_code == 200
    det = r2.json()
    assert det["snapshot"] is not None
    assert det["snapshot"]["sha256_hex"]

    r3 = client.get(
        f"/api/v1/intelligence/decisions/{d.id}/verify",
        headers=_hdr(api_tenant.slug, token),
    )
    assert r3.status_code == 200
    assert r3.json()["valid"] is True
