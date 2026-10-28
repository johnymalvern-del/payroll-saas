'''Device API-key authentication (Chapter 2A, A1).

Devices are not users. They have no password, no JWT, no refresh. A
device presents its raw key in the X-Device-Key header; the server
hashes the presented key (SHA-256 hex) and looks the device up by that
hash. The unique index on device.api_key_hash makes the lookup O(log n)
and the value is comparable with hmac.compare_digest as belt-and-braces.

Argon2 is deliberately NOT used: argon2 is salted, so a device cannot
be found by its key without scanning every row and re-hashing against
every stored hash. SHA-256 is the correct primitive for lookup-by-hash
and is fast enough for a hot path.

The raw key never leaves the server after the create/rotate response.
Only the hash is stored. A lost key means rotate-key and re-provision the
device.

On success, last_seen_at is updated. On failure, the request is
rate-limited by client IP using the existing rate limiter, so an attack
on the device-key surface cannot brute-force keys.

Failed auth returns 403 device_auth_failed (not 401: this is not a
missing-token case; the client is presenting a token that is invalid,
or inactive).
'''
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import Depends, Header, Request, status
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.rate_limiter.factory import get_rate_limiter
from app.db.tenant.models.devices import Device


def hash_device_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()


def _client_ip(request: Request) -> str:
    xff = request.headers.get('x-forwarded-for')
    if xff:
        return xff.split(',')[0].strip()
    if request.client:
        return request.client.host
    return 'unknown'


def require_device(
    request: Request,
    db: TenantDbDep,
    x_device_key: Annotated[str | None, Header(alias='X-Device-Key')] = None,
) -> Any:
    '''Verify the device API key and return the Device ORM row.

    Return type is Any, not Device, because FastAPI builds a pydantic
    schema for a dependency's declared return type and the SQLAlchemy
    Mapped[...] annotations on the ORM model are not pydantic-safe.
    Runtime value is Device.
    '''
    if not x_device_key:
        raise AppError('device_auth_failed', 'Missing X-Device-Key header', 403)
    settings = get_settings()
    ip = _client_ip(request)
    rl = get_rate_limiter()
    limit = getattr(settings, 'device_auth_rate_limit_per_minute', 20)
    if not rl.hit(f'device_auth:ip:{ip}', limit=limit, window_seconds=60):
        raise AppError('rate_limited', 'Too many device auth attempts, try again shortly', 429)
    presented = hash_device_key(x_device_key)
    candidate = db.scalar(select(Device).where(Device.api_key_hash == presented))
    if candidate is None:
        raise AppError('device_auth_failed', 'Unknown device key', 403)
    if not hmac.compare_digest(candidate.api_key_hash, presented):
        raise AppError('device_auth_failed', 'Unknown device key', 403)
    if candidate.status != 'active':
        raise AppError('device_inactive', f'Device is {candidate.status}', 403)
    candidate.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    return candidate


DeviceDep = Annotated[Any, Depends(require_device)]

# END OF FILE
