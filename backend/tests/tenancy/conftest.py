"""Fixtures for tenancy tests.

Every fixture that creates a tenant must also remove it, otherwise tenant
databases accumulate in the Postgres volume and eventually slow startup.
We bypass the CLI and call the private helpers directly.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.main import app
from app.services import provisioning as provisioning_mod
from app.services.provisioning import ProvisioningError, provision_tenant


@dataclass
class DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


def _drop_tenant(slug: str) -> None:
    """Drop the tenant DB and delete its subscriber row, best-effort."""
    with control_session() as session:
        sub = session.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
        if sub is None:
            return
        db_name = sub.tenant_db_name
        session.delete(sub)

    if db_name:
        try:
            provisioning_mod._drop_tenant_database(db_name)
        except Exception:
            pass


def _register_one(prefix: str = "tst") -> DisposableTenant:
    slug = f"{prefix}-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name=f"Tenant {slug}",
        admin_username="admin",
        admin_password_hash=hash_password("TestPassword123!"),
    )
    return DisposableTenant(
        slug=result.slug,
        tenant_db_name=result.tenant_db_name,
        subscriber_id=result.subscriber_id,
    )


@pytest.fixture()
def disposable_tenant() -> Iterator[DisposableTenant]:
    t = _register_one()
    try:
        yield t
    finally:
        _drop_tenant(t.slug)


@pytest.fixture()
def two_tenants() -> Iterator[tuple[DisposableTenant, DisposableTenant]]:
    a = _register_one("alpha")
    b = _register_one("beta")
    try:
        yield a, b
    finally:
        _drop_tenant(a.slug)
        _drop_tenant(b.slug)


@pytest.fixture()
def api_client() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client