"""A tenant whose schema_version does not match head is refused."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.main import app
from app.services.provisioning import (
    _drop_tenant_database,
    _tenant_db_name,
    provision_tenant,
)


@pytest.fixture()
def api_client() -> TestClient:
    with TestClient(app) as c:
        yield c


def test_schema_behind_tenant_refused(api_client: TestClient) -> None:
    slug = f"stb-{uuid.uuid4().hex[:10]}"
    provision_tenant(
        slug=slug,
        name="Schema Behind Co",
        admin_username="admin",
        admin_password_hash=hash_password("SomeStrongPassword123!"),
    )
    db_name = _tenant_db_name(slug)
    try:
        with control_session() as session:
            row = session.query(Subscriber).filter(Subscriber.slug == slug).one()
            row.tenant_schema_version = "ten_ffff"
        r = api_client.post(
            "/api/v1/auth/login",
            headers={"X-Tenant-Slug": slug},
            json={
                "identifier": "admin",
                "password": "SomeStrongPassword123!",
            },
        )
        assert r.status_code == 503, r.text
        assert r.json()["error"]["code"] == "tenant_schema_behind"
    finally:
        _drop_tenant_database(db_name)
        with control_session() as session:
            row = session.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if row is not None:
                session.delete(row)