
"""Auth dependencies for FastAPI endpoints."""
from __future__ import annotations

from datetime import timezone
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.api.deps import TenantDbDep, TenantDep
from app.core.auth_tokens import JWTManager, TokenError
from app.core.config import get_settings
from app.db.tenant.models.people import User

_bearer_scheme = HTTPBearer(auto_error=False)


def _auth_error(code: str = "unauthorized") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=code,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _resolve_bearer(
    creds: HTTPAuthorizationCredentials | None,
) -> str:
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise _auth_error()
    return creds.credentials


def _truncate_to_whole_seconds(dt):
    """Return dt truncated to whole seconds, timezone-aware.

    password_changed_at has microsecond precision; a JWT's iat has whole
    seconds. Without truncating, a token issued immediately after
    change-password (same second) would appear earlier than
    password_changed_at and be wrongly rejected.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(microsecond=0)


def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    tenant_ctx: TenantDep,
    db: TenantDbDep,
) -> Any:
    """Verify the access token and return the ORM User row.

    Return type is Any, not User, because FastAPI builds a pydantic schema
    for a dependency's declared return type, and the SQLAlchemy ORM model's
    Mapped[...] annotations are not pydantic-safe. Runtime value is User.
    """
    token = _resolve_bearer(creds)
    settings = get_settings()
    jwt_mgr = JWTManager(settings.secret_key)

    try:
        claims = jwt_mgr.decode(token)
    except TokenError:
        raise _auth_error() from None

    if not jwt_mgr.is_access(claims):
        raise _auth_error()

    if claims.tenant != tenant_ctx.slug:
        raise _auth_error()

    try:
        import uuid as _uuid

        user_id = _uuid.UUID(claims.user_id)
    except Exception:
        raise _auth_error() from None

    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise _auth_error()
    if not user.is_active:
        raise _auth_error()

    # Reject tokens issued before the password was last changed.
    # Truncate both sides to whole seconds so a token issued in the same
    # second as the password change is not rejected.
    truncated_changed = _truncate_to_whole_seconds(user.password_changed_at)
    if truncated_changed is not None:
        issued_at = claims.issued_at
        if issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=timezone.utc)
        if issued_at.replace(microsecond=0) < truncated_changed:
            raise _auth_error()

    if user.locked_until is not None:
        from datetime import datetime

        locked = user.locked_until
        if locked.tzinfo is None:
            locked = locked.replace(tzinfo=timezone.utc)
        if locked > datetime.now(timezone.utc):
            raise _auth_error()

    return user


def require_roles(*allowed_roles: str):
    allowed = frozenset(allowed_roles)

    def _check(user: Annotated[Any, Depends(get_current_user)]) -> Any:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
            )
        return user

    return _check


_PASSWORD_CHANGE_ALLOWED_PATHS = frozenset(
    {
        "/api/v1/auth/change-password",
        "/api/v1/auth/logout",
    }
)


def password_change_gate(
    request: Request,
    user: Annotated[Any, Depends(get_current_user)],
) -> Any:
    if not user.must_change_password:
        return user
    if request.url.path in _PASSWORD_CHANGE_ALLOWED_PATHS:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="password_change_required",
    )


def csrf_protection(
    request: Request,
    x_csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    refresh_cookie = request.cookies.get("refresh_token")
    if not refresh_cookie:
        return
    if not x_csrf_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="csrf_missing"
        )
    csrf_cookie = request.cookies.get("csrf_token")
    if not csrf_cookie or csrf_cookie != x_csrf_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="csrf_invalid"
        )
