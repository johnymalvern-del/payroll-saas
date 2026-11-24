"""Password hashing utilities (argon2-cffi).

One hasher, chosen once at import from PAYROLL_TEST_FAST_HASH. No global
mutation after that point.

History this file is deliberately replacing: three successive patch blocks
(_4A_BIS_SECURITY, _V2, _V3) each rewrote module globals at import time to
speed up hashing under test. They accumulated because each patch appeared
after the previous one had already shipped, and they overlapped:

  * v2 defined verify_password(password_hash, password) -- argument order
    inverted relative to the original
  * v3 redefined it correctly
  * v3 won only because it was defined *later in the file*

Any future reordering of those blocks would have silently inverted password
verification: a correct password rejected, or in some paths an incorrect one
accepted. Nothing tested the ordering. That is why this file is now a single
explicit branch instead of stacked monkey-patches.

The cost of the fast hasher is confined to test runs, which set
PAYROLL_TEST_FAST_HASH=1. Production parameters are argon2's defaults:
Argon2id, 64 MiB memory, time cost 3, parallelism 4.
"""
from __future__ import annotations

import os

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

MIN_PASSWORD_LENGTH = 12

# Test parameters exist so the suite is not dominated by hashing. They are
# deliberately weak (t=1, m=8 MiB) and MUST NOT be reachable in production --
# see the guard below.
_TEST_TIME_COST = 1
_TEST_MEMORY_COST = 8192
_TEST_PARALLELISM = 1


def _build_hasher() -> PasswordHasher:
    """The single hasher for this process.

    The environment switch is read exactly once, here. Nothing mutates module
    globals afterwards, so the argument order of verify_password cannot depend
    on definition order.
    """
    if os.environ.get("PAYROLL_TEST_FAST_HASH") == "1":
        return PasswordHasher(
            time_cost=_TEST_TIME_COST,
            memory_cost=_TEST_MEMORY_COST,
            parallelism=_TEST_PARALLELISM,
        )
    return PasswordHasher()


_hasher = _build_hasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Check a plaintext password against a stored argon2 hash.

    Argument order is (plain, hashed). An earlier revision of this module
    carried a monkey-patched version with the parameters reversed; that is the
    specific failure this signature and its tests guard against.
    """
    if not plain or not hashed:
        return False
    try:
        _hasher.verify(hashed, plain)
        return True
    except VerificationError:
        return False
    except Exception:
        # A malformed or truncated hash is a failed verification, not a crash.
        # argon2 raises InvalidHashError for values it cannot parse, and a
        # corrupted column must not take down a login endpoint.
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except Exception:
        return True


def password_meets_policy(plain: str) -> tuple[bool, str | None]:
    if len(plain) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    return True, None

# END OF FILE