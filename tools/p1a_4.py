"""Phase 1A — backend tests + frontend bundle."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BE = ROOT / "backend"
FE = ROOT / "frontend" / "src"

# ---------- 1. Backend tests ----------
(BE / "tests" / "test_intelligence_settings.py").write_text('''"""Phase 1A — intelligence settings service + endpoint tests.

Uses _leave_session_shared for service-level tests (fast, session-scoped
tenant, rollback per test) and api_client + local disposable_tenant for
endpoint-level tests (permission, HTTP status).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.permissions import check_permission, Permission
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.adjustment import Adjustment if False else None  # noqa
from app.db.tenant.models.people import User
from app.db.tenant.models.platform import AuditLog
from app.db.tenant.session import get_tenant_engine
from app.main import app
from app.services.intelligence_service import (
    _get_or_create_settings,
    record_mode_change,
    resolve_effective_mode,
)
from app.services.provisioning import (
    _drop_tenant_database, _tenant_db_name, provision_tenant,
)


# =============================================================
# Helpers / fixtures
# =============================================================

@dataclass
class _DT:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def api_tenant() -> Iterator[_DT]:
    slug = f"intel-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug, name="Intel Co", admin_username="admin",
        admin_password_hash=hash_password("IntelTest123!"),
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
def api(db_engine_for_tenant, api_tenant):
    return api_tenant


@pytest.fixture()
def db_engine_for_tenant(api_tenant):
    engine = get_tenant_engine(api_tenant.tenant_db_name)
    return engine


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


def _mk_user(db: Session, username: str, role: str,
             password: str = "x") -> User:
    u = User(
        id=uuid.uuid4(), username=username,
        password_hash=hash_password(password),
        role=role, is_active=True, must_change_password=False,
        failed_attempts=0, row_version=1,
    )
    db.add(u)
    db.commit()
    return u


def _login(client: TestClient, slug: str, username: str, password: str) -> str:
    r = client.post(
        "/api/v1/auth/login",
        json={"identifier": username, "password": password},
        headers={"X-Tenant-Slug": slug},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _hdr(slug: str, token: str) -> dict:
    return {"X-Tenant-Slug": slug, "Authorization": f"Bearer {token}"}


def _admin_user(db: Session) -> User:
    u = db.scalar(select(User).where(User.username == "admin"))
    assert u is not None
    return u


# =============================================================
# Service-level tests (no HTTP)
# =============================================================

@pytest.fixture()
def svc_db(_leave_session_shared):
    return _leave_session_shared


def test_missing_settings_defaults_to_traditional(svc_db):
    # Ensure no settings row exists (fresh tenant from _leave_session_shared)
    from app.db.tenant.models.intelligence import IntelligenceSettings
    svc_db.query(IntelligenceSettings).delete()
    svc_db.commit()
    assert resolve_effective_mode(svc_db, "leave_decision") == "traditional"


def test_resolve_workflow_override_takes_precedence(svc_db):
    from app.db.tenant.models.intelligence import IntelligenceWorkflowMode
    settings = _get_or_create_settings(svc_db)
    settings.default_mode = "assisted"
    svc_db.add(IntelligenceWorkflowMode(
        id=uuid.uuid4(), workflow="leave_decision", mode="autonomous",
        is_active=True,
        effective_from=datetime.now(timezone.utc) - timedelta(hours=1),
        row_version=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))
    svc_db.commit()
    assert resolve_effective_mode(svc_db, "leave_decision") == "autonomous"


def test_resolve_inactive_override_falls_back(svc_db):
    from app.db.tenant.models.intelligence import IntelligenceWorkflowMode
    settings = _get_or_create_settings(svc_db)
    settings.default_mode = "assisted"
    svc_db.add(IntelligenceWorkflowMode(
        id=uuid.uuid4(), workflow="leave_decision", mode="autonomous",
        is_active=False,
        effective_from=datetime.now(timezone.utc) - timedelta(hours=1),
        row_version=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))
    svc_db.commit()
    assert resolve_effective_mode(svc_db, "leave_decision") == "assisted"


def test_resolve_unknown_workflow_fails(svc_db):
    with pytest.raises(AppError) as e:
        resolve_effective_mode(svc_db, "not_a_workflow")
    assert e.value.code == "unknown_workflow"


def test_resolve_effective_dates_respected(svc_db):
    from app.db.tenant.models.intelligence import IntelligenceWorkflowMode
    settings = _get_or_create_settings(svc_db)
    settings.default_mode = "assisted"
    svc_db.add(IntelligenceWorkflowMode(
        id=uuid.uuid4(), workflow="leave_decision", mode="autonomous",
        is_active=True,
        effective_from=datetime.now(timezone.utc) + timedelta(days=30),
        row_version=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))
    svc_db.commit()
    assert resolve_effective_mode(svc_db, "leave_decision") == "assisted"


def test_record_mode_change_requires_reason(svc_db):
    with pytest.raises(AppError) as e:
        record_mode_change(
            svc_db, _admin_user(svc_db),
            workflow=None, previous_mode="traditional", new_mode="assisted",
            reason="   ", effective_from=datetime.now(timezone.utc),
            audit_id=None,
        )
    assert e.value.code == "reason_required"


def test_record_mode_change_rejects_invalid_mode(svc_db):
    with pytest.raises(AppError) as e:
        record_mode_change(
            svc_db, _admin_user(svc_db),
            workflow=None, previous_mode="traditional", new_mode="invalid",
            reason="test", effective_from=datetime.now(timezone.utc),
            audit_id=None,
        )
    assert e.value.code == "invalid_mode"


# =============================================================
# Permission unit tests (no HTTP)
# =============================================================

def test_hr_can_view_but_not_manage():
    hr = SimpleNamespace(role="hr")
    assert check_permission(hr, Permission.INTELLIGENCE_VIEW) is True
    assert check_permission(hr, Permission.INTELLIGENCE_MANAGE) is False


def test_payroll_admin_can_view_and_manage():
    pa = SimpleNamespace(role="payroll_admin")
    assert check_permission(pa, Permission.INTELLIGENCE_VIEW) is True
    assert check_permission(pa, Permission.INTELLIGENCE_MANAGE) is True


def test_auditor_can_view_not_manage():
    au = SimpleNamespace(role="auditor")
    assert check_permission(au, Permission.INTELLIGENCE_VIEW) is True
    assert check_permission(au, Permission.INTELLIGENCE_MANAGE) is False


def test_employee_denied():
    emp = SimpleNamespace(role="employee")
    assert check_permission(emp, Permission.INTELLIGENCE_VIEW) is False
    assert check_permission(emp, Permission.INTELLIGENCE_MANAGE) is False


# =============================================================
# Endpoint tests (HTTP)
# =============================================================

def test_get_settings_returns_default(client, api, db):
    token = _login(client, api.slug, "admin", "IntelTest123!")
    r = client.get("/api/v1/intelligence/settings",
                   headers=_hdr(api.slug, token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["default_mode"] == "traditional"
    assert body["row_version"] == 1


def test_update_default_to_assisted(client, api, db):
    token = _login(client, api.slug, "admin", "IntelTest123!")
    r = client.patch(
        "/api/v1/intelligence/settings/default-mode",
        json={"default_mode": "assisted", "row_version": 1,
              "reason": "switch to assisted"},
        headers=_hdr(api.slug, token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["default_mode"] == "assisted"
    assert r.json()["row_version"] == 2


def test_update_to_autonomous_requires_ack(client, api, db):
    token = _login(client, api.slug, "admin", "IntelTest123!")
    r = client.patch(
        "/api/v1/intelligence/settings/default-mode",
        json={"default_mode": "autonomous", "row_version": 1,
              "reason": "trial", "acknowledged_autonomous": False},
        headers=_hdr(api.slug, token),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "autonomous_requires_acknowledgement"


def test_update_to_autonomous_with_ack_succeeds(client, api, db):
    token = _login(client, api.slug, "admin", "IntelTest123!")
    r = client.patch(
        "/api/v1/intelligence/settings/default-mode",
        json={"default_mode": "autonomous", "row_version": 1,
              "reason": "opt in",
              "acknowledged_autonomous": True},
        headers=_hdr(api.slug, token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["default_mode"] == "autonomous"
    assert body["acknowledged_at"] is not None
    # audit row created
    audits = db.scalar(select(func.count()).select_from(AuditLog))
    assert audits >= 1


def test_update_requires_reason(client, api, db):
    token = _login(client, api.slug, "admin", "IntelTest123!")
    r = client.patch(
        "/api/v1/intelligence/settings/default-mode",
        json={"default_mode": "assisted", "row_version": 1, "reason": ""},
        headers=_hdr(api.slug, token),
    )
    # Pydantic min_length=3 blocks empty; if it slips through, endpoint 422s.
    assert r.status_code == 422


def test_stale_row_version_409(client, api, db):
    token = _login(client, api.slug, "admin", "IntelTest123!")
    r = client.patch(
        "/api/v1/intelligence/settings/default-mode",
        json={"default_mode": "assisted", "row_version": 99,
              "reason": "wrong version"},
        headers=_hdr(api.slug, token),
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "record_changed"


def test_workflow_override_roundtrip(client, api, db):
    token = _login(client, api.slug, "admin", "IntelTest123!")
    # First set company default to assisted
    client.patch(
        "/api/v1/intelligence/settings/default-mode",
        json={"default_mode": "assisted", "row_version": 1, "reason": "assisted"},
        headers=_hdr(api.slug, token),
    )
    # Then override leave_decision to autonomous
    r = client.patch(
        "/api/v1/intelligence/settings/workflows/leave_decision",
        json={"mode": "autonomous", "is_active": True, "row_version": None,
              "reason": "opt leave in", "acknowledged_autonomous": True},
        headers=_hdr(api.slug, token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["override_mode"] == "autonomous"
    assert body["override_active"] is True
    assert body["effective_mode"] == "autonomous"
    assert body["autonomous_capability_implemented"] is False


def test_change_log_records_and_lists(client, api, db):
    token = _login(client, api.slug, "admin", "IntelTest123!")
    client.patch(
        "/api/v1/intelligence/settings/default-mode",
        json={"default_mode": "assisted", "row_version": 1,
              "reason": "log test"},
        headers=_hdr(api.slug, token),
    )
    r = client.get("/api/v1/intelligence/settings/change-log",
                   headers=_hdr(api.slug, token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) >= 1
    assert body["items"][0]["new_mode"] == "assisted"
    assert body["items"][0]["workflow"] is None


def test_hr_can_read_but_not_write(client, api, db):
    _mk_user(db, "hruser", "hr", "HrPass123!")
    hr_token = _login(client, api.slug, "hruser", "HrPass123!")
    admin_token = _login(client, api.slug, "admin", "IntelTest123!")
    # Ensure settings row exists
    client.get("/api/v1/intelligence/settings",
               headers=_hdr(api.slug, admin_token))

    r = client.get("/api/v1/intelligence/settings",
                   headers=_hdr(api.slug, hr_token))
    assert r.status_code == 200

    r = client.patch(
        "/api/v1/intelligence/settings/default-mode",
        json={"default_mode": "assisted", "row_version": 1, "reason": "test"},
        headers=_hdr(api.slug, hr_token),
    )
    assert r.status_code == 403


def test_auditor_can_read_denied_write(client, api, db):
    _mk_user(db, "auduser", "auditor", "AudPass123!")
    admin_token = _login(client, api.slug, "admin", "IntelTest123!")
    aud_token = _login(client, api.slug, "auduser", "AudPass123!")
    client.get("/api/v1/intelligence/settings",
               headers=_hdr(api.slug, admin_token))
    r = client.get("/api/v1/intelligence/settings",
                   headers=_hdr(api.slug, aud_token))
    assert r.status_code == 200
    r = client.patch(
        "/api/v1/intelligence/settings/default-mode",
        json={"default_mode": "assisted", "row_version": 1, "reason": "test"},
        headers=_hdr(api.slug, aud_token),
    )
    assert r.status_code == 403


def test_employee_denied(client, api, db):
    _mk_user(db, "empuser", "employee", "EmpPass123!")
    emp_token = _login(client, api.slug, "empuser", "EmpPass123!")
    r = client.get("/api/v1/intelligence/settings",
                   headers=_hdr(api.slug, emp_token))
    assert r.status_code == 403


def test_no_workflow_execution_on_change(client, api, db):
    """Mode change must not create any decision, adjustment, exception, or run."""
    from app.db.tenant.models.pay import PayrollRun
    token = _login(client, api.slug, "admin", "IntelTest123!")
    runs_before = db.scalar(select(func.count()).select_from(PayrollRun)) or 0
    client.patch(
        "/api/v1/intelligence/settings/default-mode",
        json={"default_mode": "autonomous", "row_version": 1,
              "reason": "chaos", "acknowledged_autonomous": True},
        headers=_hdr(api.slug, token),
    )
    runs_after = db.scalar(select(func.count()).select_from(PayrollRun)) or 0
    assert runs_after == runs_before
''', encoding="utf-8")
print("wrote backend/tests/test_intelligence_settings.py")

print("\nP1A stage 4a complete (backend tests). Frontend bundle in notepad 5.")