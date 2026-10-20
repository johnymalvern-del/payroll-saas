"""Tenant resolution and context management.

Priority of resolution (highest first):
  1. X-Tenant-Slug header (dev/test only; enforced by config)
  2. Subdomain of the request hostname, if it ends in .{TENANT_ROOT_DOMAIN}
  3. `tenant` claim on the JWT (Phase 1C - stubbed here)

Once the slug is known, this module loads the subscriber, checks that it is
active, verifies the schema version matches the current Alembic head, and
exposes the per-tenant encryption key to the rest of the request lifecycle.
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from starlette.requests import Request

from app.core.config import get_settings
from app.core.logging import get_logger, tenant_slug_ctx
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.encryption import clear_tenant_key, set_tenant_key, unseal_with_master

log = get_logger("app.core.tenant_routing")


# ---------------------------------------------------------------------------
# Exceptions (mapped to HTTP status codes by api/deps.py)
# ---------------------------------------------------------------------------


class TenantError(Exception):
    """Base for all tenant resolution errors."""


class TenantNotSpecified(TenantError):
    """No tenant slug could be determined from the request."""


class TenantNotFound(TenantError):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Tenant '{slug}' not found")


class TenantInactive(TenantError):
    def __init__(self, slug: str, status: str) -> None:
        self.slug = slug
        self.status = status
        super().__init__(f"Tenant '{slug}' is not active (status={status})")


class TenantNotProvisioned(TenantError):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Tenant '{slug}' has no database yet")


class TenantSchemaBehind(TenantError):
    def __init__(self, slug: str, current: str, expected: str) -> None:
        self.slug = slug
        self.current = current
        self.expected = expected
        super().__init__(
            f"Tenant '{slug}' schema {current!r} is behind head {expected!r}"
        )


# ---------------------------------------------------------------------------
# TenantContext
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TenantContext:
    subscriber_id: uuid.UUID
    slug: str
    tenant_db_name: str
    schema_version: str
    encryption_key: bytes


current_tenant: ContextVar[TenantContext | None] = ContextVar(
    "current_tenant", default=None
)


def get_current_tenant() -> TenantContext:
    ctx = current_tenant.get()
    if ctx is None:
        raise RuntimeError("No tenant context active for this request")
    return ctx


# ---------------------------------------------------------------------------
# Alembic head revision (cached per process)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_head_revision() -> str:
    backend_dir = Path(__file__).resolve().parent.parent.parent
    cfg = AlembicConfig(str(backend_dir / "alembic.ini"), ini_section="tenant")
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    if not head:
        raise RuntimeError("Tenant Alembic directory has no head revision")
    return head


# ---------------------------------------------------------------------------
# Resolution: which slug is the request asking for?
# ---------------------------------------------------------------------------


def _root_domain() -> str:
    """Base domain for subdomain parsing. Defaults to localhost in dev/test."""
    env = get_settings().environment
    return "localhost" if env in ("development", "test") else "example.com"


def _slug_from_subdomain(request: Request) -> str | None:
    hostname = (request.url.hostname or "").lower()
    root = _root_domain()
    if hostname == root or not hostname.endswith("." + root):
        return None
    prefix = hostname[: -len(root) - 1]
    if not prefix or "." in prefix:
        return None
    return prefix


def _slug_from_header(request: Request) -> str | None:
    settings = get_settings()
    if not settings.tenant_header_fallback_active:
        return None
    slug = request.headers.get("X-Tenant-Slug", "").strip().lower()
    return slug or None


def _slug_from_jwt(request: Request) -> str | None:
    # Phase 1C will populate request.state.jwt_claims. For now, no-op.
    claims = getattr(request.state, "jwt_claims", None)
    if isinstance(claims, dict):
        slug = claims.get("tenant")
        if isinstance(slug, str) and slug:
            return slug.lower()
    return None


def resolve_slug(request: Request) -> str | None:
    # Priority order matches the docstring at the top of this module.
    return (
        _slug_from_header(request)
        or _slug_from_subdomain(request)
        or _slug_from_jwt(request)
    )


# ---------------------------------------------------------------------------
# Load subscriber + validate + decrypt key
# ---------------------------------------------------------------------------


def load_tenant_context(slug: str) -> TenantContext:
    head = get_head_revision()
    with control_session() as session:
        sub = (
            session.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
        )
        if sub is None:
            raise TenantNotFound(slug)
        if sub.status != "active":
            raise TenantInactive(slug, sub.status)
        if not sub.tenant_db_name:
            raise TenantNotProvisioned(slug)
        if sub.tenant_schema_version != head:
            raise TenantSchemaBehind(slug, sub.tenant_schema_version or "", head)
        key_str = unseal_with_master(sub.encryption_key_encrypted)
        return TenantContext(
            subscriber_id=sub.id,
            slug=sub.slug,
            tenant_db_name=sub.tenant_db_name,
            schema_version=sub.tenant_schema_version,
            encryption_key=key_str.encode("ascii"),
        )


@contextmanager
def tenant_context(slug: str) -> Iterator[TenantContext]:
    """Set up and tear down the tenant ContextVars for one request.

    Guarantees cleanup even on exception, so a thread that served tenant A
    can never leak tenant A's encryption key into the next request.
    """
    ctx = load_tenant_context(slug)
    token = tenant_slug_ctx.set(ctx.slug)
    set_tenant_key(ctx.encryption_key)
    current_tenant.set(ctx)
    log.debug("tenant.context.enter", slug=ctx.slug)
    try:
        yield ctx
    finally:
        current_tenant.set(None)
        clear_tenant_key()
        tenant_slug_ctx.reset(token)
        log.debug("tenant.context.exit", slug=ctx.slug)