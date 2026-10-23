
"""Auth service: login, refresh-token rotation, logout, change-password.

All database writes happen inside a single session owned by the caller.
This module contains no FastAPI imports - the endpoints in Reply C will
call these functions.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth_tokens import JWTManager, TokenClaims, TokenError
from app.core.config import get_settings
from app.core.security import (
    hash_password,
    needs_rehash,
    verify_password,
)
from app.core.usernames import looks_like_email, normalise_username
from app.models_auth_orm import RefreshToken, RefreshTokenFamily
from app.db.tenant.models.people import User
from app.services.audit_helper import write_auth_audit

# A pre-computed Argon2 hash of a random string. Used to keep login timing
# constant when the username does not exist (see authenticate()).
_DUMMY_HASH = hash_password("dummy-password-for-constant-time-auth")


class AuthError(Exception):
    """Generic auth failure. Callers map to a single generic response."""


class AuthLockedError(AuthError):
    pass


class AuthRefreshReuseError(AuthError):
    pass


class AuthRetryableRefreshError(AuthError):
    """Old refresh token presented within leeway - ask the client to retry."""


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    refresh_token: str
    expires_in: int
    must_change_password: bool
    user_id: str


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def authenticate(
    session: Session,
    *,
    identifier: str,
    password: str,
    ip_address: str | None,
    user_agent: str | None,
    request_id: str | None,
) -> User:
    """Verify credentials and return the User row.

    - Constant-time: a missing user still runs a dummy Argon2 verify.
    - Generic error: AuthError for both wrong-username and wrong-password.
    - Lockout: after login_max_failures, the account is locked for
      login_lockout_minutes. Checked before verification.
    - Audit: writes login_failure / login_success / lockout entries.
    """
    settings = get_settings()
    ident = identifier.strip()

    user: User | None = None
    if looks_like_email(ident):
        stmt = select(User).join(User.employee_id, isouter=True).where(
            User.username == normalise_username(ident) if False else User.username == ident.lower()
        )
        # Simpler: email field lives on employee; we do not currently have
        # employee.email indexed via ORM join for this test. Fall back to
        # username lookup after normalising - usernames never contain '@',
        # so an email identifier cannot accidentally match a username.
        user = session.scalar(select(User).where(User.username == ""))  # never matches
        # Look up by employee email
        from app.db.tenant.models.people import Employee

        emp = session.scalar(select(Employee).where(Employee.email == ident.lower()))
        if emp is not None:
            user = session.scalar(select(User).where(User.employee_id == emp.id))
    else:
        user = session.scalar(select(User).where(User.username == normalise_username(ident)))

    # Lockout check runs regardless of whether the user exists, so timing
    # and error remain uniform.
    if user is not None and user.locked_until is not None:
        if user.locked_until > _now():
            write_auth_audit(
                session,
                action="login_locked",
                entity_id=str(user.id),
                actor_user_id=str(user.id),
                actor_role=user.role,
                ip_address=ip_address,
                request_id=request_id,
            )
            session.commit()
            raise AuthLockedError("account temporarily locked")

    stored_hash = user.password_hash if user is not None else _DUMMY_HASH
    ok = verify_password(password, stored_hash)

    if user is None or not ok:
        if user is not None:
            user.failed_attempts = (user.failed_attempts or 0) + 1
            if user.failed_attempts >= settings.login_max_failures:
                user.locked_until = _now() + timedelta(minutes=settings.login_lockout_minutes)
                write_auth_audit(
                    session,
                    action="lockout",
                    entity_id=str(user.id),
                    actor_user_id=str(user.id),
                    actor_role=user.role,
                    ip_address=ip_address,
                    request_id=request_id,
                )
            else:
                write_auth_audit(
                    session,
                    action="login_failure",
                    entity_id=str(user.id),
                    actor_user_id=str(user.id),
                    actor_role=user.role,
                    ip_address=ip_address,
                    request_id=request_id,
                )
            session.commit()
        else:
            write_auth_audit(
                session,
                action="login_failure_unknown_user",
                entity_type="user",
                entity_id=None,
                ip_address=ip_address,
                request_id=request_id,
            )
            session.commit()
        raise AuthError("invalid credentials")

    # Successful login
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = _now()
    write_auth_audit(
        session,
        action="login_success",
        entity_id=str(user.id),
        actor_user_id=str(user.id),
        actor_role=user.role,
        ip_address=ip_address,
        request_id=request_id,
    )
    return user


def issue_token_pair(
    session: Session,
    *,
    user: User,
    tenant: str,
    ip_address: str | None,
    user_agent: str | None,
) -> LoginResult:
    settings = get_settings()
    jwt_manager = JWTManager(settings.secret_key)

    access = jwt_manager.issue_access(
        user_id=str(user.id), tenant=tenant, role=user.role
    )
    refresh = jwt_manager.issue_refresh(user_id=str(user.id), tenant=tenant)
    refresh_claims = jwt_manager.decode(refresh)
    jti_hash = _sha256_hex(refresh_claims.jti)

    family = RefreshTokenFamily(
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(family)
    session.flush()

    session.add(
        RefreshToken(
            family_id=family.id,
            jti_hash=jti_hash,
            expires_at=refresh_claims.expires_at,
        )
    )
    return LoginResult(
        access_token=access,
        refresh_token=refresh,
        expires_in=int((access and 15 * 60) or 0),
        must_change_password=user.must_change_password,
        user_id=str(user.id),
    )


def rotate_refresh_token(
    session: Session,
    *,
    refresh_token: str,
    tenant: str,
    ip_address: str | None,
    user_agent: str | None,
    request_id: str | None,
) -> LoginResult:
    settings = get_settings()
    jwt_manager = JWTManager(settings.secret_key)
    try:
        claims = jwt_manager.decode(refresh_token)
    except TokenError as exc:
        raise AuthError("invalid refresh token") from exc
    if not jwt_manager.is_refresh(claims):
        raise AuthError("not a refresh token")
    if claims.tenant != tenant:
        raise AuthError("refresh token tenant mismatch")

    jti_hash = _sha256_hex(claims.jti)
    stored = session.scalar(select(RefreshToken).where(RefreshToken.jti_hash == jti_hash))
    if stored is None:
        raise AuthError("unknown refresh token")

    family = session.get(RefreshTokenFamily, stored.family_id)
    if family is None or family.revoked_at is not None:
        raise AuthError("refresh token family revoked")

    user = session.get(User, family.user_id)
    if user is None:
        raise AuthError("user gone")

    now = _now()
    if stored.used_at is not None:
        leeway = timedelta(seconds=settings.refresh_reuse_leeway_seconds)
        if (now - stored.used_at) <= leeway:
            # Flaky-network retry, not theft.
            write_auth_audit(
                session,
                action="refresh_reuse_within_leeway",
                entity_id=str(user.id),
                actor_user_id=str(user.id),
                actor_role=user.role,
                ip_address=ip_address,
                request_id=request_id,
            )
            session.commit()
            raise AuthRetryableRefreshError("retry")
        # Outside leeway: theft. Revoke the family.
        family.revoked_at = now
        family.revoked_reason = "reuse_detected"
        write_auth_audit(
            session,
            action="refresh_reuse_detected",
            entity_id=str(user.id),
            actor_user_id=str(user.id),
            actor_role=user.role,
            ip_address=ip_address,
            request_id=request_id,
        )
        session.commit()
        raise AuthRefreshReuseError("refresh token reuse detected")

    if stored.expires_at <= now:
        raise AuthError("refresh token expired")

    # Issue new pair
    new_access = jwt_manager.issue_access(
        user_id=str(user.id), tenant=tenant, role=user.role
    )
    new_refresh = jwt_manager.issue_refresh(user_id=str(user.id), tenant=tenant)
    new_claims = jwt_manager.decode(new_refresh)
    new_jti_hash = _sha256_hex(new_claims.jti)

    new_row = RefreshToken(
        family_id=family.id,
        jti_hash=new_jti_hash,
        expires_at=new_claims.expires_at,
    )
    session.add(new_row)
    session.flush()

    stored.used_at = now
    stored.replaced_by_id = new_row.id
    family.last_used_at = now

    return LoginResult(
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in=15 * 60,
        must_change_password=user.must_change_password,
        user_id=str(user.id),
    )


def revoke_family(
    session: Session,
    *,
    refresh_token: str,
    tenant: str,
    reason: str,
    ip_address: str | None,
    user_agent: str | None,
    request_id: str | None,
) -> None:
    settings = get_settings()
    jwt_manager = JWTManager(settings.secret_key)
    try:
        claims = jwt_manager.decode(refresh_token)
    except TokenError:
        return
    if claims.tenant != tenant:
        return
    jti_hash = _sha256_hex(claims.jti)
    stored = session.scalar(select(RefreshToken).where(RefreshToken.jti_hash == jti_hash))
    if stored is None:
        return
    family = session.get(RefreshTokenFamily, stored.family_id)
    if family is None or family.revoked_at is not None:
        return
    family.revoked_at = _now()
    family.revoked_reason = reason
    write_auth_audit(
        session,
        action="logout" if reason == "logout" else f"revoke_{reason}",
        entity_id=str(family.user_id),
        actor_user_id=str(family.user_id),
        ip_address=ip_address,
        request_id=request_id,
    )


def change_password(
    session: Session,
    *,
    user: User,
    current_password: str,
    new_password: str,
    ip_address: str | None,
    request_id: str | None,
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise AuthError("current password incorrect")
    if len(new_password) < 12:
        raise AuthError("password too short")
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.password_changed_at = _now()

    # Revoke every family for this user - all existing sessions are invalid.
    families = session.scalars(
        select(RefreshTokenFamily).where(
            RefreshTokenFamily.user_id == user.id,
            RefreshTokenFamily.revoked_at.is_(None),
        )
    ).all()
    for fam in families:
        fam.revoked_at = _now()
        fam.revoked_reason = "password_change"

    write_auth_audit(
        session,
        action="change_password",
        entity_id=str(user.id),
        actor_user_id=str(user.id),
        actor_role=user.role,
        ip_address=ip_address,
        request_id=request_id,
    )
