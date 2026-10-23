
"""Cross-tenant isolation: data, crypto, and unknown-slug handling.

Proves:
1. Two tenants cannot see each other's rows (different physical databases).
2. A TenantCrypto key is genuinely per-tenant (ciphertext from A does not
   decrypt with B's key) and survives a fresh session.
3. Looking up an unknown slug raises TenantNotFound.
4. The TenantContext carries a working crypto object - the design that
   replaces the old ContextVar approach and is safe across thread boundaries.
"""
from __future__ import annotations

import uuid

import pytest
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

from app.core.tenant_routing import (
    load_tenant_context,
    tenant_context,
)
from app.db.tenant.session import tenant_session


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

    with tenant_context(a.slug):
        with tenant_session(a.tenant_db_name) as s:
            codes_a = [r[0] for r in s.execute(text("SELECT code FROM branch")).all()]
    with tenant_context(b.slug):
        with tenant_session(b.tenant_db_name) as s:
            codes_b = [r[0] for r in s.execute(text("SELECT code FROM branch")).all()]

    assert branch_a_code in codes_a
    assert branch_b_code not in codes_a
    assert branch_b_code in codes_b
    assert branch_a_code not in codes_b


def test_encrypted_columns_use_per_tenant_key(two_tenants) -> None:
    a, b = two_tenants
    ctx_a = load_tenant_context(a.slug)
    ctx_b = load_tenant_context(b.slug)

    # Each TenantContext carries its own crypto object bound to a distinct key.
    plaintext = "very-sensitive-popi-data"
    ciphertext = ctx_a.crypto.encrypt(plaintext)
    assert ciphertext is not None
    # Decrypt back through the SAME context: the plaintext round-trips.
    assert ctx_a.crypto.decrypt(ciphertext) == plaintext

    # Tenant B's key cannot decrypt tenant A's ciphertext.
    from app.core.crypto import CryptoKeyMissing  # noqa: F401 - kept for clarity

    with pytest.raises(RuntimeError, match="decrypt"):
        # ctx_b.crypto has a valid key, but it is a *different* key, so Fernet
        # will raise InvalidToken internally; our wrapper turns it into a
        # plain RuntimeError with a clear message and no secret leaked.
        ctx_b.crypto.decrypt(ciphertext)


def test_tenant_context_carries_working_crypto(disposable_tenant) -> None:
    """The new design carries the crypto key on the TenantContext.

    This is the whole point of replacing the ContextVar: the value travels
    with the context object, so a request handled on any thread sees the
    same key. Prove it works end-to-end here, not just in isolation.
    """
    t = disposable_tenant
    ctx = load_tenant_context(t.slug)
    assert ctx.crypto is not None

    ciphertext = ctx.crypto.encrypt("payload-for-round-trip")
    assert ciphertext is not None and ciphertext != "payload-for-round-trip"

    # Round-trip through a completely fresh TenantContext (simulates a new
    # request, possibly on a different thread).
    ctx2 = load_tenant_context(t.slug)
    assert ctx2.crypto.decrypt(ciphertext) == "payload-for-round-trip"


def test_load_tenant_context_rejects_unknown_slug() -> None:
    from app.core.tenant_routing import TenantNotFound

    with pytest.raises(TenantNotFound):
        load_tenant_context(f"doesnotexist-{uuid.uuid4().hex[:8]}")