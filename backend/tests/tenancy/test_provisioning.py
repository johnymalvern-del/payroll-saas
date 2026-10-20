"""Provisioning: success, duplicate rejection, invalid input, rollback."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.services import provisioning as provisioning_mod
from app.services.provisioning import (
    ProvisioningError,
    _drop_tenant_database,
    _tenant_db_name,
    provision_tenant,
)


def _db_exists(db_name: str) -> bool:
    admin_engine = create_engine(
        provisioning_mod._admin_url("postgres"),
        isolation_level="AUTOCOMMIT",
        future=True,
    )
    try:
        with admin_engine.connect() as conn:
            n = conn.scalar(
                text("SELECT count(*) FROM pg_database WHERE datname = :d"),
                {"d": db_name},
            )
        return bool(n)
    finally:
        admin_engine.dispose()


def _subscriber_by_slug(slug: str) -> Subscriber | None:
    with control_session() as session:
        return session.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()


# ---------------------------------------------------------------------------
# HTTP registration endpoint
# ---------------------------------------------------------------------------


def test_register_endpoint_creates_working_tenant(api_client: TestClient) -> None:
    slug = f"http-{uuid.uuid4().hex[:10]}"
    r = api_client.post(
        "/api/v1/register",
        json={
            "company_name": "Endpoint Test Ltd",
            "slug": slug,
            "admin_username": "admin",
            "admin_password": "EndpointPassword123!",
        },
    )
    try:
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["slug"] == slug
        assert body["tenant_db_name"] == _tenant_db_name(slug)
        assert body["schema_version"] == "ten_0001"

        sub = _subscriber_by_slug(slug)
        assert sub is not None
        assert sub.status == "active"
        assert sub.tenant_schema_version == "ten_0001"
        assert _db_exists(sub.tenant_db_name)
    finally:
        _drop_tenant_database(_tenant_db_name(slug))
        with control_session() as session:
            row = session.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if row is not None:
                session.delete(row)


def test_register_rejects_duplicate_slug(
    api_client: TestClient, disposable_tenant,
) -> None:
    r = api_client.post(
        "/api/v1/register",
        json={
            "company_name": "Duplicate Co",
            "slug": disposable_tenant.slug,
            "admin_username": "admin2",
            "admin_password": "AnotherPassword123!",
        },
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "provisioning_failed"
    assert "already taken" in body["error"]["message"]


def test_register_rejects_invalid_slug(api_client: TestClient) -> None:
    r = api_client.post(
        "/api/v1/register",
        json={
            "company_name": "Bad Slug Co",
            "slug": "UPPERCASE",
            "admin_username": "admin",
            "admin_password": "WhateverPassword123!",
        },
    )
    assert r.status_code == 400
    assert "Invalid slug" in r.json()["error"]["message"]


def test_register_rejects_reserved_slug(api_client: TestClient) -> None:
    r = api_client.post(
        "/api/v1/register",
        json={
            "company_name": "Reserved Co",
            "slug": "admin",
            "admin_username": "admin",
            "admin_password": "WhateverPassword123!",
        },
    )
    assert r.status_code == 400
    assert "reserved" in r.json()["error"]["message"]


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def test_rollback_drops_database_when_provisioning_fails(monkeypatch) -> None:
    """If _create_first_admin raises, the tenant DB must be dropped and the
    subscriber marked failed. Nothing is left behind."""
    slug = f"rb-{uuid.uuid4().hex[:10]}"

    def exploding_create_admin(*_args, **_kwargs) -> None:
        raise RuntimeError("simulated failure during admin creation")

    monkeypatch.setattr(
        provisioning_mod, "_create_first_admin", exploding_create_admin
    )

    with pytest.raises(ProvisioningError) as exc_info:
        provision_tenant(
            slug=slug,
            name="Rollback Co",
            admin_username="admin",
            admin_password_hash=hash_password("TestPassword123!"),
        )
    assert "simulated failure" in str(exc_info.value)

    # Subscriber row exists but is marked failed with an error message
    sub = _subscriber_by_slug(slug)
    assert sub is not None
    assert sub.status == "failed"
    assert sub.provisioning_status == "failed"
    assert "simulated failure" in (sub.provisioning_error or "")

    # Tenant database must have been dropped
    assert not _db_exists(_tenant_db_name(slug))

    # Cleanup the subscriber row
    with control_session() as session:
        row = session.query(Subscriber).filter(Subscriber.slug == slug).one()
        session.delete(row)


# ---------------------------------------------------------------------------
# Slug validation edge cases (via the endpoint, which returns 400)
# ---------------------------------------------------------------------------


def test_password_policy_enforced(api_client: TestClient) -> None:
    r = api_client.post(
        "/api/v1/register",
        json={
            "company_name": "Short Pw Co",
            "slug": "shortpw",
            "admin_username": "admin",
            "admin_password": "short",
        },
    )
    assert r.status_code in (400, 422)
    code = r.json()["error"]["code"]
    assert code in {"weak_password", "validation_error"}