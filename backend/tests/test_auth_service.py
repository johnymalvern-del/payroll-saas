
"""Auth-service tests that do not need endpoints.

Four tests:
  1. Constant-time login: unknown-user and known-user-with-wrong-password
     take comparable wall time (both run Argon2), proving no account
     enumeration via timing.
  2. Refresh reuse within leeway: presenting an already-used refresh token
     within refresh_reuse_leeway_seconds returns AuthRetryableRefreshError
     and does NOT revoke the family.
  3. Refresh reuse outside leeway: presenting an already-used refresh token
     after the leeway returns AuthRefreshReuseError and DOES revoke the
     family.
  4. change_password sets password_changed_at and revokes every family.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.tenant.models.people import User
from app.models_auth_orm import RefreshToken, RefreshTokenFamily
from app.services import auth_service
from app.services.auth_service import (
    AuthError,
    AuthRefreshReuseError,
    AuthRetryableRefreshError,
    authenticate,
    change_password,
    issue_token_pair,
    rotate_refresh_token,
)


# ---------------------------------------------------------------------------
# Local fixtures that do NOT need the control DB - they create a fresh tenant
# database using provisioning, then hand back a Session bound to it.
# ---------------------------------------------------------------------------

@pytest.fixture()
def tenant_session():
    """Provision a fresh tenant database, yield (slug, db_name, session)."""
    from app.services.provisioning import (
        _drop_tenant_database,
        _tenant_db_name,
        provision_tenant,
    )

    slug = f"as-{uuid.uuid4().hex[:10]}"
    provision_tenant(
        slug=slug,
        name="Auth Service Test Co",
        admin_username="admin",
        admin_password_hash=hash_password("InitialPassword123!"),
    )
    db_name = _tenant_db_name(slug)
    from app.db.tenant.session import get_tenant_engine

    engine = get_tenant_engine(db_name)
    session = Session(engine)
    try:
        yield slug, db_name, session
    finally:
        session.close()
        _drop_tenant_database(db_name)
        from app.db.control.models import Subscriber
        from app.db.control.session import control_session

        with control_session() as ctl:
            row = ctl.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if row is not None:
                ctl.delete(row)


def _admin_user(session: Session) -> User:
    return session.query(User).filter(User.role == "payroll_admin").one()


def test_constant_time_login(tenant_session) -> None:
    _slug, _db, session = tenant_session

    # Warm up both paths once so Argon2's first-call overhead is not
    # counted on the timed runs.
    try:
        authenticate(
            session,
            identifier="admin",
            password="wrong",
            ip_address="127.0.0.1",
            user_agent="pytest",
            request_id=None,
        )
    except AuthError:
        pass
    try:
        authenticate(
            session,
            identifier="no-such-user",
            password="wrong",
            ip_address="127.0.0.1",
            user_agent="pytest",
            request_id=None,
        )
    except AuthError:
        pass

    N = 3

    t0 = time.perf_counter()
    for _ in range(N):
        try:
            authenticate(
                session,
                identifier="admin",
                password="wrong",
                ip_address="127.0.0.1",
                user_agent="pytest",
                request_id=None,
            )
        except AuthError:
            pass
    known_wrong_time = time.perf_counter() - t0

    t0 = time.perf_counter()
    for _ in range(N):
        try:
            authenticate(
                session,
                identifier="no-such-user",
                password="wrong",
                ip_address="127.0.0.1",
                user_agent="pytest",
                request_id=None,
            )
        except AuthError:
            pass
    unknown_time = time.perf_counter() - t0

    # Both paths run Argon2. Allow a generous 3x ratio to account for
    # noise on Windows, but a broken implementation (no dummy verify on the
    # unknown-user path) would be 10x-100x faster. Anything outside
    # [0.33x, 3x] fails the test.
    ratio = unknown_time / known_wrong_time if known_wrong_time > 0 else 1.0
    assert 0.33 < ratio < 3.0, f"timing ratio {ratio:.2f} suggests no dummy hash"


def test_reuse_within_leeway_does_not_revoke(tenant_session, monkeypatch) -> None:
    slug, db_name, session = tenant_session
    # Force a long leeway so the second use is definitely inside it.
    settings = get_settings()
    monkeypatch.setattr(settings, "refresh_reuse_leeway_seconds", 60, raising=False)

    user = _admin_user(session)
    pair = issue_token_pair(
        session,
        user=user,
        tenant=slug,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    session.commit()

    # First use - rotate. Old token becomes used_at.
    rotated = rotate_refresh_token(
        session,
        refresh_token=pair.refresh_token,
        tenant=slug,
        ip_address="127.0.0.1",
        user_agent="pytest",
        request_id=None,
    )
    session.commit()

    # Second use of the OLD token - should be within leeway.
    with pytest.raises(AuthRetryableRefreshError):
        rotate_refresh_token(
            session,
            refresh_token=pair.refresh_token,
            tenant=slug,
            ip_address="127.0.0.1",
            user_agent="pytest",
            request_id=None,
        )

    # Family must still be valid: the NEW token works.
    again = rotate_refresh_token(
        session,
        refresh_token=rotated.refresh_token,
        tenant=slug,
        ip_address="127.0.0.1",
        user_agent="pytest",
        request_id=None,
    )
    assert again.access_token


def test_reuse_outside_leeway_revokes_family(tenant_session, monkeypatch) -> None:
    slug, db_name, session = tenant_session
    # Force a tiny leeway so the second use is definitely outside it.
    settings = get_settings()
    monkeypatch.setattr(settings, "refresh_reuse_leeway_seconds", 0, raising=False)

    user = _admin_user(session)
    pair = issue_token_pair(
        session,
        user=user,
        tenant=slug,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    session.commit()

    rotated = rotate_refresh_token(
        session,
        refresh_token=pair.refresh_token,
        tenant=slug,
        ip_address="127.0.0.1",
        user_agent="pytest",
        request_id=None,
    )
    session.commit()

    # Sleep 1.1s so the "leeway 0" is definitely exceeded.
    time.sleep(1.1)

    with pytest.raises(AuthRefreshReuseError):
        rotate_refresh_token(
            session,
            refresh_token=pair.refresh_token,
            tenant=slug,
            ip_address="127.0.0.1",
            user_agent="pytest",
            request_id=None,
        )
    session.commit()

    # Family must now be revoked: the NEW token no longer works.
    with pytest.raises(AuthError):
        rotate_refresh_token(
            session,
            refresh_token=rotated.refresh_token,
            tenant=slug,
            ip_address="127.0.0.1",
            user_agent="pytest",
            request_id=None,
        )


def test_change_password_sets_timestamp_and_revokes_families(tenant_session) -> None:
    slug, db_name, session = tenant_session
    user = _admin_user(session)
    original_pwd_hash = user.password_hash
    user.must_change_password = True
    session.commit()

    pair = issue_token_pair(
        session,
        user=user,
        tenant=slug,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    session.commit()

    before = datetime.now(timezone.utc)
    change_password(
        session,
        user=user,
        current_password="InitialPassword123!",
        new_password="NewPasswordForTest!",
        ip_address="127.0.0.1",
        request_id=None,
    )
    session.commit()
    session.refresh(user)

    assert user.password_changed_at is not None
    assert user.password_changed_at >= before - timedelta(seconds=1)
    assert user.must_change_password is False
    assert user.password_hash != original_pwd_hash

    # All families for this user must be revoked.
    families = (
        session.query(RefreshTokenFamily)
        .filter(RefreshTokenFamily.user_id == user.id)
        .all()
    )
    assert len(families) >= 1
    for fam in families:
        assert fam.revoked_at is not None
        assert fam.revoked_reason == "password_change"

    # The refresh token issued before the change must no longer rotate.
    with pytest.raises(AuthError):
        rotate_refresh_token(
            session,
            refresh_token=pair.refresh_token,
            tenant=slug,
            ip_address="127.0.0.1",
            user_agent="pytest",
            request_id=None,
        )
