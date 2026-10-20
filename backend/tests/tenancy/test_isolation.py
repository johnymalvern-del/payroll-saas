"""Cross-tenant isolation: data, encryption keys, and context cleanup.

These tests prove the guarantees the brief requires:

1. Two tenants cannot see each other's rows, because they live in different
   physical databases.
2. A ciphertext produced by tenant A cannot be decrypted with tenant B's key.
3. After a tenant context exits, the key ContextVar is cleared and any
   attempt to use it raises RuntimeError. No cross-request leakage.
"""
from __future__ import annotations

import uuid

import pytest
from cryptography.fernet import InvalidToken, Fernet
from sqlalchemy import text

from app.core.tenant_routing import (
    current_tenant,
    load_tenant_context,
    tenant_context,
)
from app.db.encryption import get_tenant_key, set_tenant_key, clear_tenant_key
from app.db.tenant.session import tenant_session


# ---------------------------------------------------------------------------
# Data isolation
# ---------------------------------------------------------------------------


def test_two_tenants_see_only_their_own_rows(two_tenants) -> None:
    a, b = two_tenants
    branch_a_code = f"A-{uuid.uuid4().hex[:8]}"
    branch_b_code = f"B-{uuid.uuid4().hex[:8]}"

    with tenant_context(a.slug):
        with tenant_session(a.tenant_db_name) as s:
            s.execute(
                text(
                    "INSERT INTO branch (id, name, code) "
                    "VALUES (:id, :name, :code)"
                ),
                {"id": str(uuid.uuid4()), "name": "Branch A", "code": branch_a_code},
            )
    with tenant_context(b.slug):
        with tenant_session(b.tenant_db_name) as s:
            s.execute(
                text(
                    "INSERT INTO branch (id, name, code) "
                    "VALUES (:id, :name, :code)"
                ),
                {"id": str(uuid.uuid4()), "name": "Branch B", "code": branch_b_code},
            )

    # Each tenant sees only its own row
    with tenant_context(a.slug):
        with tenant_session(a.tenant_db_name) as s:
            codes_a = [
                r[0] for r in s.execute(text("SELECT code FROM branch")).all()
            ]
    with tenant_context(b.slug):
        with tenant_session(b.tenant_db_name) as s:
            codes_b = [
                r[0] for r in s.execute(text("SELECT code FROM branch")).all()
            ]

    assert branch_a_code in codes_a
    assert branch_b_code not in codes_a
    assert branch_b_code in codes_b
    assert branch_a_code not in codes_b


# ---------------------------------------------------------------------------
# Key isolation
# ---------------------------------------------------------------------------


def test_encrypted_columns_use_per_tenant_key(two_tenants) -> None:
    a, b = two_tenants

    # Encrypt a message with tenant A's key
    ctx_a = load_tenant_context(a.slug)
    ctx_b = load_tenant_context(b.slug)

    assert ctx_a.encryption_key != ctx_b.encryption_key

    plaintext = "very-sensitive-popi-data"
    ciphertext = Fernet(ctx_a.encryption_key).encrypt(plaintext.encode("utf-8"))

    # Tenant A's key can decrypt it; tenant B's key cannot
    assert Fernet(ctx_a.encryption_key).decrypt(ciphertext).decode("utf-8") == plaintext
    with pytest.raises(InvalidToken):
        Fernet(ctx_b.encryption_key).decrypt(ciphertext)


# ---------------------------------------------------------------------------
# Context cleanup (no cross-request leakage on a shared thread)
# ---------------------------------------------------------------------------


def test_context_cleanup_after_exit(disposable_tenant) -> None:
    t = disposable_tenant

    # Before entering any context, no key is set
    clear_tenant_key()
    with pytest.raises(RuntimeError):
        get_tenant_key()

    # Inside the context, the key is available and current_tenant is set
    with tenant_context(t.slug) as ctx:
        assert get_tenant_key() == ctx.encryption_key
        assert current_tenant.get() is not None
        assert current_tenant.get().slug == t.slug

    # After exit, everything is cleared — no leakage into the next request
    assert current_tenant.get() is None
    with pytest.raises(RuntimeError):
        get_tenant_key()


def test_load_tenant_context_rejects_unknown_slug() -> None:
    from app.core.tenant_routing import TenantNotFound

    with pytest.raises(TenantNotFound):
        load_tenant_context(f"doesnotexist-{uuid.uuid4().hex[:8]}")