
"""Auth endpoints: login, refresh, logout, change-password."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import TenantDbDep, TenantDep
from app.api.v1.auth.schemas import (
    ChangePasswordIn,
    LoginIn,
    RefreshIn,
    TokenPairOut,
)
from app.core.auth_deps import csrf_protection, get_current_user
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.rate_limiter.factory import get_rate_limiter
from app.services import auth_service
from app.services.auth_service import (
    AuthError,
    AuthLockedError,
    AuthRefreshReuseError,
    AuthRetryableRefreshError,
    authenticate,
    change_password,
    issue_token_pair,
    revoke_family,
    rotate_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE = "refresh_token"
_CSRF_COOKIE = "csrf_token"
_REFRESH_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


def _is_production_mode() -> bool:
    return get_settings().environment in ("staging", "production")


def _client_ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _issue_cookies(response: Response, refresh_token: str, csrf_token: str) -> None:
    secure = _is_production_mode()
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=secure,
        samesite="strict",
        max_age=_REFRESH_MAX_AGE_SECONDS,
        path="/",
    )
    response.set_cookie(
        key=_CSRF_COOKIE,
        value=csrf_token,
        httponly=False,
        secure=secure,
        samesite="strict",
        max_age=_REFRESH_MAX_AGE_SECONDS,
        path="/",
    )


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(key=_REFRESH_COOKIE, path="/")
    response.delete_cookie(key=_CSRF_COOKIE, path="/")


def _pair_response(result: auth_service.LoginResult) -> TokenPairOut:
    return TokenPairOut(
        access_token=result.access_token,
        refresh_token=result.refresh_token if not _is_production_mode() else "",
        token_type="bearer",
        expires_in=result.expires_in,
    )


@router.post("/login", response_model=TokenPairOut)
def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: TenantDbDep,
    tenant: TenantDep,
) -> TokenPairOut:
    ip = _client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:300] or None

    rl = get_rate_limiter()
    if not rl.hit(
        f"login:ip:{ip or 'unknown'}",
        limit=get_settings().login_rate_limit_per_minute,
        window_seconds=60,
    ):
        raise AppError(
            "rate_limited",
            "Too many login attempts, try again shortly",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    try:
        user = authenticate(
            db,
            identifier=payload.identifier,
            password=payload.password,
            ip_address=ip,
            user_agent=ua,
            request_id=getattr(request.state, "request_id", None),
        )
        result = issue_token_pair(
            db,
            user=user,
            tenant=tenant.slug,
            ip_address=ip,
            user_agent=ua,
        )
        db.commit()
    except AuthLockedError:
        raise AppError(
            "account_locked",
            "Account is temporarily locked",
            status.HTTP_423_LOCKED,
        ) from None
    except AuthError:
        raise AppError(
            "invalid_credentials",
            "Invalid username or password",
            status.HTTP_401_UNAUTHORIZED,
        ) from None

    if _is_production_mode():
        import secrets

        csrf = secrets.token_urlsafe(32)
        _issue_cookies(response, result.refresh_token, csrf)
    return _pair_response(result)


@router.post("/refresh", response_model=TokenPairOut,
             dependencies=[Depends(csrf_protection)])
def refresh(
    payload: RefreshIn,
    request: Request,
    response: Response,
    db: TenantDbDep,
    tenant: TenantDep,
) -> TokenPairOut:
    ip = _client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:300] or None
    token = payload.refresh_token or request.cookies.get(_REFRESH_COOKIE) or ""
    if not token:
        raise AppError(
            "refresh_missing", "No refresh token provided", status.HTTP_400_BAD_REQUEST
        )

    try:
        result = rotate_refresh_token(
            db,
            refresh_token=token,
            tenant=tenant.slug,
            ip_address=ip,
            user_agent=ua,
            request_id=getattr(request.state, "request_id", None),
        )
        db.commit()
    except AuthRetryableRefreshError:
        raise AppError(
            "refresh_retry",
            "Refresh just rotated, retry with the new token",
            status.HTTP_409_CONFLICT,
        ) from None
    except AuthRefreshReuseError:
        raise AppError(
            "refresh_reuse",
            "Refresh token reuse detected; session revoked",
            status.HTTP_401_UNAUTHORIZED,
        ) from None
    except AuthError:
        raise AppError(
            "refresh_invalid", "Refresh token invalid", status.HTTP_401_UNAUTHORIZED
        ) from None

    if _is_production_mode():
        import secrets

        csrf = secrets.token_urlsafe(32)
        _issue_cookies(response, result.refresh_token, csrf)
    return _pair_response(result)


@router.post("/logout", status_code=status.HTTP_200_OK,
             dependencies=[Depends(csrf_protection)])
async def logout(
    request: Request,
    response: Response,
    db: TenantDbDep,
    tenant: TenantDep,
) -> dict[str, str]:
    """Revoke the current refresh-token family and clear cookies.

    In production the refresh token is in the httpOnly cookie; in dev/test it
    is in the JSON body (because tests use TestClient without cookies). Try
    cookie first, then body. If neither is present there is nothing to revoke
    but the caller still gets a clean 200 so an already-logged-out session
    does not error.
    """
    token = request.cookies.get(_REFRESH_COOKIE)
    if not token:
        try:
            body = await request.json()
        except Exception:
            body = None
        if isinstance(body, dict):
            token = body.get("refresh_token")
    if token:
        revoke_family(
            db,
            refresh_token=token,
            tenant=tenant.slug,
            reason="logout",
            ip_address=_client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:300] or None,
            request_id=getattr(request.state, "request_id", None),
        )
        db.commit()
    _clear_cookies(response)
    return {"status": "logged_out"}


@router.post("/change-password", status_code=status.HTTP_200_OK)
def change_password_endpoint(
    payload: ChangePasswordIn,
    request: Request,
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
) -> dict[str, str]:
    try:
        change_password(
            db,
            user=user,
            current_password=payload.current_password,
            new_password=payload.new_password,
            ip_address=_client_ip(request),
            request_id=getattr(request.state, "request_id", None),
        )
        db.commit()
    except AuthError:
        raise AppError(
            "password_change_failed",
            "Current password incorrect or new password too weak",
            status.HTTP_400_BAD_REQUEST,
        ) from None
    return {"status": "ok"}
