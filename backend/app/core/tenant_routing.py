
"""Tenant resolution and context management.

Priority of resolution (highest first):
  1. X-Tenant-Slug header (dev/test only; enforced by config)
  2. Subdomain of the request hostname, if it ends in .{TENANT_ROOT_DOMAIN}
  3. `tenant` claim on the JWT

Note: this module intentionally keeps NO ContextVar for the tenant
context or the encryption key. FastAPI runs sync `def` dependencies and
sync `def` endpoints on anyio worker threads, and context variables set
in one worker thread are invisible in another. The tenant context is
carried as an explicit parameter (TenantDep); the encryption key is
carried as a TenantCrypto object on the context.
"""
from __future__ import annotations

import uuid  # noqa: F401 - required because TenantContext.subscriber_id is uuid.UUID

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from starlette.requests import Request

from app.core.config import get_settings
from app.core.crypto import TenantCrypto
from app.core.logging import get_logger
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.encryption import unseal_with_master

log = get_logger("app.core.tenant_routing")


class TenantError(Exception):
    """Base for all tenant resolution errors."""


class TenantNotSpecified(TenantError):
    pass


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


@dataclass(frozen=True)
class TenantContext:
    subscriber_id: uuid.UUID
    slug: str
    tenant_db_name: str
    schema_version: str
    crypto: TenantCrypto


@lru_cache(maxsize=1)
def get_head_revision() -> str:
    backend_dir = Path(__file__).resolve().parent.parent.parent
    cfg = AlembicConfig(str(backend_dir / "alembic.ini"), ini_section="tenant")
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    if not head:
        raise RuntimeError("Tenant Alembic directory has no head revision")
    return head


def _root_domain() -> str:
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
    claims = getattr(request.state, "jwt_claims", None)
    if isinstance(claims, dict):
        slug = claims.get("tenant")
        if isinstance(slug, str) and slug:
            return slug.lower()
    return None


def resolve_slug(request: Request) -> str | None:
    return (
        _slug_from_header(request)
        or _slug_from_subdomain(request)
        or _slug_from_jwt(request)
    )


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
            crypto=TenantCrypto(key_str.encode("ascii")),
        )


@contextmanager
def tenant_context(slug: str) -> Iterator[TenantContext]:
    """Resolve the tenant and yield its context.

    No ContextVar is set or reset anywhere. The context travels as a
    plain Python object through the dependency chain and into the
    endpoint. This is safe across anyio thread boundaries.
    """
    ctx = load_tenant_context(slug)
    log.debug("tenant.context.enter", slug=ctx.slug)
    try:
        yield ctx
    finally:
        log.debug("tenant.context.exit", slug=ctx.slug)
