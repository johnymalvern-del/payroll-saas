
"""Company CRUD endpoint tests."""
from __future__ import annotations

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


ADMIN_PASSWORD = "CompanyAdmin123!"


@pytest.fixture()
def company_tenant(api_client: TestClient):
    from app.db.tenant.models.people import User
    from app.db.tenant.session import tenant_session

    slug = f"cmp-{uuid.uuid4().hex[:10]}"
    provision_tenant(
        slug=slug,
        name="Company CRUD Co",
        admin_username="admin",
        admin_password_hash=hash_password(ADMIN_PASSWORD),
    )
    db_name = _tenant_db_name(slug)
    try:
        with tenant_session(db_name) as s:
            for role in ("employee", "manager", "hr", "auditor"):
                s.add(
                    User(
                        username=f"test-{role}",
                        password_hash=hash_password("RolePassword123!"),
                        role=role,
                        is_active=True,
                        must_change_password=False,
                    )
                )

        r = api_client.post(
            "/api/v1/auth/login",
            headers={"X-Tenant-Slug": slug},
            json={"identifier": "admin", "password": ADMIN_PASSWORD},
        )
        assert r.status_code == 200, r.text
        admin_token = r.json()["access_token"]

        tokens: dict[str, str] = {"payroll_admin": admin_token}
        for role in ("employee", "manager", "hr", "auditor"):
            rr = api_client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": slug},
                json={"identifier": f"test-{role}", "password": "RolePassword123!"},
            )
            assert rr.status_code == 200, rr.text
            tokens[role] = rr.json()["access_token"]

        yield slug, tokens, db_name
    finally:
        _drop_tenant_database(db_name)
        with control_session() as session:
            row = session.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if row is not None:
                session.delete(row)


def _h(slug: str, token: str | None = None) -> dict[str, str]:
    headers = {"X-Tenant-Slug": slug}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _current_version(api_client: TestClient, slug: str, token: str) -> int:
    r = api_client.get("/api/v1/company", headers=_h(slug, token))
    assert r.status_code == 200, r.text
    return r.json()["row_version"]


def test_get_company_requires_auth(api_client: TestClient, company_tenant) -> None:
    slug, _tokens, _db = company_tenant
    r = api_client.get("/api/v1/company", headers=_h(slug))
    assert r.status_code == 401


def test_get_company_by_role_matrix(api_client: TestClient, company_tenant) -> None:
    slug, tokens, _db = company_tenant
    for role, expected_status in (
        ("employee", 200),
        ("manager", 200),
        ("hr", 200),
        ("payroll_admin", 200),
        ("auditor", 403),
    ):
        r = api_client.get("/api/v1/company", headers=_h(slug, tokens[role]))
        assert r.status_code == expected_status, f"{role}: {r.text}"
        if expected_status == 200:
            body = r.json()
            assert body["legal_name"] == "Company CRUD Co"
            assert body["row_version"] == 1


def test_patch_company_role_gate(api_client: TestClient, company_tenant) -> None:
    """Every role attempts one PATCH. Denied roles never touch version.
    Allowed roles bump version, so re-read before each attempt."""
    slug, tokens, _db = company_tenant
    for role, expected_status in (
        ("employee", 403),
        ("manager", 403),
        ("auditor", 403),
        ("hr", 200),
        ("payroll_admin", 200),
    ):
        v = _current_version(api_client, slug, tokens["payroll_admin"])
        r = api_client.patch(
            "/api/v1/company",
            headers=_h(slug, tokens[role]),
            json={"row_version": v, "trading_name": f"Name by {role}"},
        )
        assert r.status_code == expected_status, f"{role}: {r.text}"


def test_patch_company_row_version_conflict(api_client: TestClient, company_tenant) -> None:
    slug, tokens, _db = company_tenant
    v = _current_version(api_client, slug, tokens["payroll_admin"])
    r1 = api_client.patch(
        "/api/v1/company",
        headers=_h(slug, tokens["payroll_admin"]),
        json={"row_version": v, "trading_name": "First"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["row_version"] == v + 1

    r2 = api_client.patch(
        "/api/v1/company",
        headers=_h(slug, tokens["payroll_admin"]),
        json={"row_version": v, "trading_name": "Second"},
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["error"]["code"] == "record_changed"


def test_patch_company_hr_forbidden_for_payroll_admin_only_fields(
    api_client: TestClient, company_tenant
) -> None:
    slug, tokens, _db = company_tenant
    v = _current_version(api_client, slug, tokens["payroll_admin"])
    r = api_client.patch(
        "/api/v1/company",
        headers=_h(slug, tokens["hr"]),
        json={"row_version": v, "tax_number": "9001234567"},
    )
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "forbidden_field"


def test_patch_company_payroll_admin_can_set_tax_number(
    api_client: TestClient, company_tenant
) -> None:
    slug, tokens, _db = company_tenant
    v = _current_version(api_client, slug, tokens["payroll_admin"])
    r = api_client.patch(
        "/api/v1/company",
        headers=_h(slug, tokens["payroll_admin"]),
        json={"row_version": v, "tax_number": "9001234567"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["tax_number"] == "9001234567"


def test_patch_company_writes_audit_row(api_client: TestClient, company_tenant) -> None:
    from app.db.tenant.session import tenant_session
    from sqlalchemy import text

    slug, tokens, db_name = company_tenant
    v = _current_version(api_client, slug, tokens["payroll_admin"])
    r = api_client.patch(
        "/api/v1/company",
        headers=_h(slug, tokens["payroll_admin"]),
        json={"row_version": v, "trading_name": "Audit Test", "tax_number": "9009999999"},
    )
    assert r.status_code == 200, r.text

    with tenant_session(db_name) as s:
        rows = s.execute(
            text(
                "SELECT old_value, new_value FROM audit_log "
                "WHERE entity_type = 'company' AND action = 'company.update' "
                "ORDER BY occurred_at DESC LIMIT 1"
            )
        ).all()
    assert len(rows) == 1
    old_value, new_value = rows[0]
    assert new_value.get("tax_number") == "9009999999"
    assert new_value.get("trading_name") == "Audit Test"
    # old_value.tax_number must be empty (None or "") before this update.
    assert old_value.get("tax_number") in (None, "")
