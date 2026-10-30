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

# --- 4A-bis: _4A_BIS_SECURITY: weak argon2 in test env only; production unchanged ---
import os as _os_4a_sec
from argon2 import PasswordHasher as _PH_4a_sec

if _os_4a_sec.environ.get("PAYROLL_TEST_FAST_HASH") == "1":
    _4a_fast = _PH_4a_sec(time_cost=1, memory_cost=8192, parallelism=1, hash_len=16, salt_len=8)
    for _4a_n in list(globals().keys()):
        _4a_o = globals().get(_4a_n)
        if isinstance(_4a_o, _PH_4a_sec) and _4a_o is not _4a_fast:
            globals()[_4a_n] = _4a_fast

def _4a_current_hasher():
    for _4a_n in ("_hasher", "_PH", "_password_hasher", "password_hasher", "_HASHER"):
        _4a_o = globals().get(_4a_n)
        if isinstance(_4a_o, _PH_4a_sec):
            return _4a_o
    return _PH_4a_sec()
# --- end ---


# --- 4A-bis v2: _4A_BIS_SECURITY_V2: robust override ---
import os as _os_v2_sec
from argon2 import PasswordHasher as _PH_v2_sec
from argon2.exceptions import VerifyMismatchError as _VME_v2_sec

if _os_v2_sec.environ.get("PAYROLL_TEST_FAST_HASH") == "1":
    _4a_fast_v2 = _PH_v2_sec(time_cost=1, memory_cost=8192, parallelism=1, hash_len=16, salt_len=8)
    for _n_v2 in list(globals().keys()):
        _v_v2 = globals().get(_n_v2)
        if isinstance(_v_v2, _PH_v2_sec) and _v_v2 is not _4a_fast_v2:
            globals()[_n_v2] = _4a_fast_v2
    if callable(globals().get("hash_password")):
        def hash_password(password):  # type: ignore[no-redef]
            return _4a_fast_v2.hash(password)
    if callable(globals().get("verify_password")):
        def verify_password(password_hash, password):  # type: ignore[no-redef]
            try:
                return _4a_fast_v2.verify(password_hash, password)
            except _VME_v2_sec:
                return False

def _4a_current_hasher():
    if _os_v2_sec.environ.get("PAYROLL_TEST_FAST_HASH") == "1":
        return _4a_fast_v2
    return _PH_v2_sec()
# --- end 4A-bis v2 ---


# --- 4A-bis v3: _4A_BIS_SECURITY_V3: fix v2 arg-order bug ---
import os as _os_v3
from argon2 import PasswordHasher as _PH_v3

_4a_fast_v3 = _PH_v3(time_cost=1, memory_cost=8192, parallelism=1, hash_len=16, salt_len=8)

_v3_prev_hash = globals().get("hash_password")
_v3_prev_verify = globals().get("verify_password")

if _os_v3.environ.get("PAYROLL_TEST_FAST_HASH") == "1":
    for _n_v3 in list(globals().keys()):
        _v_v3 = globals().get(_n_v3)
        if isinstance(_v_v3, _PH_v3) and _v_v3 is not _4a_fast_v3:
            globals()[_n_v3] = _4a_fast_v3

    def hash_password(password):  # type: ignore[no-redef]
        return _4a_fast_v3.hash(password)

    def verify_password(password, stored_hash):  # type: ignore[no-redef]
        try:
            return _4a_fast_v3.verify(stored_hash, password)
        except Exception:
            return False

def _4a_current_hasher():
    if _os_v3.environ.get("PAYROLL_TEST_FAST_HASH") == "1":
        return _4a_fast_v3
    for _n_v3 in ("_hasher", "_PH", "_password_hasher", "password_hasher", "_HASHER"):
        _v_v3 = globals().get(_n_v3)
        if isinstance(_v_v3, _PH_v3):
            return _v_v3
    return _PH_v3()
# --- end 4A-bis v3 ---

# END OF FILE
