
"""Tests for password_changed_at vs iat invalidation.

Addition 2 from the C2 approval:
  * After change-password, a NEW access token issued in the same second
    must WORK, because iat and password_changed_at are truncated to whole
    seconds before comparison.
  * An OLD access token (issued in a PRIOR second) must be REJECTED.

The tests must cross a whole-second boundary where they expect rejection,
otherwise the truncation logic correctly allows the token.
"""
from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limiter.factory import get_rate_limiter
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.services.provisioning import (
    _drop_tenant_database,
    _tenant_db_name,
    provision_tenant,
)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rl = get_rate_limiter()
    if hasattr(rl, "_events"):
        rl._events.clear()  # type: ignore[attr-defined]
    yield
    if hasattr(rl, "_events"):
        rl._events.clear()  # type: ignore[attr-defined]


@pytest.fixture()
def tenant_for_invalidation(api_client: TestClient):
    slug = f"inv-{uuid.uuid4().hex[:10]}"
    provision_tenant(
        slug=slug,
        name="Invalidation Co",
        admin_username="admin",
        admin_password_hash=hash_password("OldPassword123!"),
    )
    db_name = _tenant_db_name(slug)
    try:
        r = api_client.post(
            "/api/v1/auth/login",
            headers={"X-Tenant-Slug": slug},
            json={"identifier": "admin", "password": "OldPassword123!"},
        )
        assert r.status_code == 200, r.text
        yield slug, r.json()
    finally:
        _drop_tenant_database(db_name)
        with control_session() as session:
            row = session.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if row is not None:
                session.delete(row)


def test_new_access_token_works_immediately_after_change_password(
    api_client: TestClient, tenant_for_invalidation
) -> None:
    slug, first = tenant_for_invalidation

    r = api_client.post(
        "/api/v1/auth/change-password",
        headers={"X-Tenant-Slug": slug, "Authorization": f"Bearer {first['access_token']}"},
        json={"current_password": "OldPassword123!", "new_password": "NewPassword456!"},
    )
    assert r.status_code == 200, r.text

    # New login yields a fresh token, issued in the same second as the change.
    r2 = api_client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": slug},
        json={"identifier": "admin", "password": "NewPassword456!"},
    )
    assert r2.status_code == 200, r2.text
    new_token = r2.json()["access_token"]

    # The new token must WORK immediately on a protected endpoint.
    r3 = api_client.post(
        "/api/v1/auth/change-password",
        headers={"X-Tenant-Slug": slug, "Authorization": f"Bearer {new_token}"},
        json={"current_password": "NewPassword456!", "new_password": "ThirdPassword789!"},
    )
    assert r3.status_code == 200, r3.text


def test_old_access_token_rejected_after_change_password(
    api_client: TestClient, tenant_for_invalidation
) -> None:
    slug, first = tenant_for_invalidation
    old_token = first["access_token"]

    # Sleep past a whole-second boundary so password_changed_at is strictly
    # greater than iat of `old_token`. Without this sleep the truncation rule
    # correctly allows the token (same-second boundary) and this test would be
    # testing the wrong thing.
    time.sleep(1.1)

    r = api_client.post(
        "/api/v1/auth/change-password",
        headers={"X-Tenant-Slug": slug, "Authorization": f"Bearer {old_token}"},
        json={"current_password": "OldPassword123!", "new_password": "NewPassword456!"},
    )
    assert r.status_code == 200, r.text

    # The old token was issued BEFORE the change (previous second); reject.
    r2 = api_client.post(
        "/api/v1/auth/change-password",
        headers={"X-Tenant-Slug": slug, "Authorization": f"Bearer {old_token}"},
        json={"current_password": "NewPassword456!", "new_password": "ThirdPassword789!"},
    )
    assert r2.status_code == 401, r2.text
