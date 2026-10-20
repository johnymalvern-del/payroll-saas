"""Password hashing utilities (argon2-cffi, approved change from passlib)."""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

_ph = PasswordHasher()  # defaults: Argon2id, memory 64MB, time 3, parallelism 4

MIN_PASSWORD_LENGTH = 12


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _ph.verify(hashed, plain)
        return True
    except VerificationError:
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _ph.check_needs_rehash(hashed)
    except Exception:
        return True


def password_meets_policy(plain: str) -> tuple[bool, str | None]:
    if len(plain) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    return True, None