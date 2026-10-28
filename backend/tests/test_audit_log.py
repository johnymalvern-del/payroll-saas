"""Audit-log read API tests (1C.12), part 1 of 2.

Declares its own disposable_tenant and uses api_client from tests/conftest.py.
Not in _REAL_LIMITER_MODULES, so the 1C.6.2 rate-limiter bypass applies.

Part 1: fixtures, helpers, permission table, default window, explicit range,
invalid range, and the seven filters.
Part 2 (script 2b): cursor, include_total, single-row 200/404, read-audit
rows, and the redacted-field test.

Read-auditing (D6A) writes one audit_log.read row per request. Tests in this
module that call the list endpoint and then query audit_log must account for
that row. The `_count_test_rows` helper filters by action != "audit_log.read"
so read-audit rows do not confuse filter assertions.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.usernames import normalise_username
from app.db.tenant.models.people import User
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

    slug = f"audt-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Audit Log Test Co",
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
            row = (
                session.query(Subscriber)
                .filter(Subscriber.slug == slug)
                .one_or_none()
            )
            if row is not None:
                session.delete(row)


@pytest.fixture()
def api(api_client: TestClient, disposable_tenant: _DisposableTenant):
    return api_client, disposable_tenant


@pytest.fixture()
def db(disposable_tenant: _DisposableTenant) -> Iterator[Session]:
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()


def _login(client: TestClient, slug: str, username: str, password: str) -> str:
    r = client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": slug},
        json={"identifier": username, "password": password},
    )
    assert r.status_code == 200, r.text
    token = r.json().get("access_token")
    assert token, r.text
    return token


def _auth(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Tenant-Slug": slug}


def _mk_user(
    session: Session,
    *,
    username: str,
    role: str,
    password: str,
) -> User:
    u = User(
        username=normalise_username(username),
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        must_change_password=False,
        employee_id=None,
        row_version=1,
    )
    session.add(u)
    session.commit()
    return u


def _mk_audit_row(
    session: Session,
    *,
    action: str = "test.action",
    entity_type: str = "test",
    entity_id: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    request_id: str | None = None,
    reason: str | None = None,
    old_value: dict | None = None,
    new_value: dict | None = None,
    occurred_at: datetime | None = None,
) -> AuditLog:
    row = AuditLog(
        id=uuid.uuid4(),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        request_id=request_id,
        reason=reason,
        old_value=old_value,
        new_value=new_value,
        occurred_at=occurred_at or datetime.now(timezone.utc),
    )
    session.add(row)
    session.commit()
    return row


@pytest.fixture()
def pa_token(api, db):
    client, tenant = api
    _mk_user(db, username="pa-log", role="payroll_admin", password="PaLogPassword123!")
    return _login(client, tenant.slug, "pa-log", "PaLogPassword123!")


# ---------------------------------------------------------------------------
# Permission table (D2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role,username,password,expected",
    [
        ("payroll_admin", "perm-pa", "PermPaPassword12!", 200),
        ("auditor", "perm-aud", "PermAudPassword12!", 200),
        ("hr", "perm-hr", "PermHrPassword123!", 403),
        ("manager", "perm-mgr", "PermMgrPassword12!", 403),
        ("employee", "perm-emp", "PermEmpPassword12!", 403),
    ],
)
def test_list_permission_table(api, db, role, username, password, expected):
    client, tenant = api
    _mk_user(db, username=username, role=role, password=password)
    tok = _login(client, tenant.slug, username, password)
    r = client.get("/api/v1/audit-log", headers=_auth(tok, tenant.slug))
    assert r.status_code == expected, r.text


def test_list_requires_auth(api):
    client, tenant = api
    r = client.get("/api/v1/audit-log", headers={"X-Tenant-Slug": tenant.slug})
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# Default window (D3 override)
# ---------------------------------------------------------------------------


def test_default_window_is_last_30_days(api, db, pa_token):
    client, tenant = api
    _mk_audit_row(db, action="recent", occurred_at=datetime.now(timezone.utc) - timedelta(days=1))
    r = client.get("/api/v1/audit-log", headers=_auth(pa_token, tenant.slug))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) >= 1
    from datetime import datetime as _dt
    frm = _dt.fromisoformat(body["occurred_from_applied"].replace("Z", "+00:00"))
    to = _dt.fromisoformat(body["occurred_to_applied"].replace("Z", "+00:00"))
    delta = to - frm
    assert timedelta(days=29) < delta < timedelta(days=31)


def test_default_window_excludes_old_rows(api, db, pa_token):
    client, tenant = api
    old = datetime.now(timezone.utc) - timedelta(days=60)
    _mk_audit_row(db, action="ancient", occurred_at=old)
    r = client.get("/api/v1/audit-log", headers=_auth(pa_token, tenant.slug))
    assert r.status_code == 200, r.text
    actions = [item["action"] for item in r.json()["items"]]
    assert "ancient" not in actions


def test_explicit_range_honored(api, db, pa_token):
    client, tenant = api
    old = datetime.now(timezone.utc) - timedelta(days=45)
    _mk_audit_row(db, action="seen", occurred_at=old)
    frm = (old - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to = (old + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = client.get(
        f"/api/v1/audit-log?occurred_from={frm}&occurred_to={to}",
        headers=_auth(pa_token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    actions = [item["action"] for item in r.json()["items"]]
    assert "seen" in actions


def test_invalid_range_is_400(api, pa_token):
    client, tenant = api
    r = client.get(
        "/api/v1/audit-log?occurred_from=2026-10-01T00:00:00Z&occurred_to=2026-09-01T00:00:00Z",
        headers=_auth(pa_token, tenant.slug),
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_range"


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_filter_by_actor_role(api, db, pa_token):
    client, tenant = api
    _mk_audit_row(db, action="a1", actor_role="hr")
    _mk_audit_row(db, action="a2", actor_role="payroll_admin")
    r = client.get("/api/v1/audit-log?actor_role=hr", headers=_auth(pa_token, tenant.slug))
    assert r.status_code == 200, r.text
    actions = [i["action"] for i in r.json()["items"]]
    assert "a1" in actions and "a2" not in actions


def test_filter_by_entity_type(api, db, pa_token):
    client, tenant = api
    _mk_audit_row(db, action="x1", entity_type="employee")
    _mk_audit_row(db, action="x2", entity_type="branch")
    r = client.get("/api/v1/audit-log?entity_type=employee", headers=_auth(pa_token, tenant.slug))
    assert r.status_code == 200, r.text
    actions = [i["action"] for i in r.json()["items"]]
    assert "x1" in actions and "x2" not in actions


def test_filter_by_entity_id(api, db, pa_token):
    client, tenant = api
    target_id = str(uuid.uuid4())
    _mk_audit_row(db, action="e1", entity_id=target_id)
    _mk_audit_row(db, action="e2", entity_id=str(uuid.uuid4()))
    r = client.get(f"/api/v1/audit-log?entity_id={target_id}", headers=_auth(pa_token, tenant.slug))
    assert r.status_code == 200, r.text
    actions = [i["action"] for i in r.json()["items"]]
    assert "e1" in actions and "e2" not in actions


def test_filter_by_action(api, db, pa_token):
    client, tenant = api
    _mk_audit_row(db, action="branch.create")
    _mk_audit_row(db, action="branch.delete")
    r = client.get("/api/v1/audit-log?action=branch.create", headers=_auth(pa_token, tenant.slug))
    assert r.status_code == 200, r.text
    actions = [i["action"] for i in r.json()["items"]]
    assert "branch.create" in actions and "branch.delete" not in actions


def test_filter_by_request_id(api, db, pa_token):
    client, tenant = api
    _mk_audit_row(db, action="r1", request_id="req-abc")
    _mk_audit_row(db, action="r2", request_id="req-xyz")
    r = client.get("/api/v1/audit-log?request_id=req-abc", headers=_auth(pa_token, tenant.slug))
    assert r.status_code == 200, r.text
    actions = [i["action"] for i in r.json()["items"]]
    assert "r1" in actions and "r2" not in actions


def test_filter_by_reason(api, db, pa_token):
    client, tenant = api
    _mk_audit_row(db, action="ra1", reason="device_down")
    _mk_audit_row(db, action="ra2", reason="forgot_punch")
    r = client.get("/api/v1/audit-log?reason=device_down", headers=_auth(pa_token, tenant.slug))
    assert r.status_code == 200, r.text
    actions = [i["action"] for i in r.json()["items"]]
    assert "ra1" in actions and "ra2" not in actions


def test_filter_by_actor_user_id(api, db, pa_token):
    client, tenant = api
    marker = f"aud-{uuid.uuid4().hex[:8]}"
    other = _mk_user(db, username="other-user", role="hr", password="OtherUserPass12!")
    _mk_audit_row(db, action="au1", entity_type=marker, actor_user_id=other.id)
    _mk_audit_row(db, action="au2", entity_type=marker, actor_user_id=None)
    r = client.get(
        f"/api/v1/audit-log?actor_user_id={other.id}&entity_type={marker}",
        headers=_auth(pa_token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    actions = [i["action"] for i in r.json()["items"]]
    assert "au1" in actions and "au2" not in actions


# ---------------------------------------------------------------------------
# Cursor and include_total
# ---------------------------------------------------------------------------


def test_cursor_pagination(api, db, pa_token):
    client, tenant = api
    marker = f"pag-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    for i in range(3):
        _mk_audit_row(
            db,
            action=f"page-{i}",
            entity_type=marker,
            occurred_at=now - timedelta(hours=i),
        )
    r1 = client.get(
        f"/api/v1/audit-log?limit=2&entity_type={marker}",
        headers=_auth(pa_token, tenant.slug),
    )
    assert r1.status_code == 200, r1.text
    r1p = r1.json()
    first_actions = [i["action"] for i in r1p["items"]]
    assert first_actions == ["page-0", "page-1"], first_actions
    assert r1p["next_cursor"] is not None

    r2 = client.get(
        f"/api/v1/audit-log?limit=2&cursor={r1p['next_cursor']}&entity_type={marker}",
        headers=_auth(pa_token, tenant.slug),
    )
    assert r2.status_code == 200, r2.text
    r2p = r2.json()
    second_actions = [i["action"] for i in r2p["items"]]
    assert second_actions == ["page-2"], second_actions
    assert r2p["next_cursor"] is None


def test_invalid_cursor_is_400(api, pa_token):
    client, tenant = api
    r = client.get(
        "/api/v1/audit-log?cursor=not-a-cursor",
        headers=_auth(pa_token, tenant.slug),
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_cursor"


def test_include_total(api, db, pa_token):
    client, tenant = api
    _mk_audit_row(db, action="t1", entity_type="total-test")
    _mk_audit_row(db, action="t2", entity_type="total-test")
    _mk_audit_row(db, action="t3", entity_type="other")
    r = client.get(
        "/api/v1/audit-log?include_total=true&entity_type=total-test",
        headers=_auth(pa_token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2


# ---------------------------------------------------------------------------
# Single-row read
# ---------------------------------------------------------------------------


def test_get_audit_entry_ok(api, db, pa_token):
    client, tenant = api
    row = _mk_audit_row(db, action="single-read", entity_type="test")
    r = client.get(
        f"/api/v1/audit-log/{row.id}",
        headers=_auth(pa_token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == str(row.id)
    assert body["action"] == "single-read"


def test_get_audit_entry_unknown_is_404(api, pa_token):
    client, tenant = api
    r = client.get(
        f"/api/v1/audit-log/{uuid.uuid4()}",
        headers=_auth(pa_token, tenant.slug),
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "audit_entry_not_found"


# ---------------------------------------------------------------------------
# Read-auditing (D6A)
# ---------------------------------------------------------------------------


def _read_audit_rows(db: Session) -> list[AuditLog]:
    return (
        db.query(AuditLog)
        .filter(AuditLog.action == "audit_log.read")
        .order_by(AuditLog.occurred_at.asc())
        .all()
    )


def test_read_audit_row_for_list(api, db, pa_token):
    client, tenant = api
    before = len(_read_audit_rows(db))
    r = client.get("/api/v1/audit-log", headers=_auth(pa_token, tenant.slug))
    assert r.status_code == 200, r.text
    after_rows = _read_audit_rows(db)
    assert len(after_rows) == before + 1
    new_row = after_rows[-1]
    assert new_row.entity_type == "audit_log"
    assert new_row.actor_role == "payroll_admin"
    assert new_row.old_value is None
    assert new_row.new_value is not None
    assert "filters" in new_row.new_value
    # Filters recorded are the effective range and the (empty) filter set.
    filters = new_row.new_value["filters"]
    assert "occurred_from" in filters
    assert "occurred_to" in filters
    assert filters["actor_user_id"] is None
    assert filters["action"] is None


def test_read_audit_row_for_single(api, db, pa_token):
    client, tenant = api
    row = _mk_audit_row(db, action="for-single-read")
    before = len(_read_audit_rows(db))
    r = client.get(
        f"/api/v1/audit-log/{row.id}",
        headers=_auth(pa_token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    after_rows = _read_audit_rows(db)
    assert len(after_rows) == before + 1
    new_row = after_rows[-1]
    assert new_row.old_value is None
    assert new_row.new_value is not None
    assert new_row.new_value.get("entry_id") == str(row.id)
    assert new_row.entity_id == str(row.id)


def test_read_audit_does_not_copy_payload(api, db, pa_token):
    """The read-audit row must not contain old_value/new_value of the row
    being read."""
    client, tenant = api
    _mk_audit_row(
        db,
        action="payload-check",
        old_value={"password": "[redacted]", "field": "old-stuff"},
        new_value={"field": "new-stuff"},
    )
    r = client.get(
        "/api/v1/audit-log?action=payload-check",
        headers=_auth(pa_token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    new_row = _read_audit_rows(db)[-1]
    assert new_row.old_value is None
    # new_value only carries filter metadata, not the payload we just read.
    blob = str(new_row.new_value)
    assert "old-stuff" not in blob
    assert "new-stuff" not in blob


# ---------------------------------------------------------------------------
# D7: redacted fields are shown as stored
# ---------------------------------------------------------------------------


def test_redacted_field_returned_as_stored(api, db, pa_token):
    client, tenant = api
    _mk_audit_row(
        db,
        action="redact-check",
        old_value={"password": "[redacted]", "visible": "yes"},
        new_value={"password": "[redacted]", "visible": "changed"},
    )
    r = client.get(
        "/api/v1/audit-log?action=redact-check",
        headers=_auth(pa_token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["old_value"]["password"] == "[redacted]"
    assert item["old_value"]["visible"] == "yes"
    assert item["new_value"]["password"] == "[redacted]"
    assert item["new_value"]["visible"] == "changed"

# END OF FILE