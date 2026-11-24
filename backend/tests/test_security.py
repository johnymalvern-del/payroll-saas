"""Password hashing tests.

The reason this file exists is narrower than "test the security module": an
earlier revision of app/core/security.py carried three stacked monkey-patch
blocks that each redefined hash_password and verify_password at import time.
The second one had verify_password's arguments reversed, and the third only
fixed it by being defined later in the file.

Nothing tested that. A reordering of those blocks would have inverted password
verification -- rejecting correct passwords, and in some code paths accepting
incorrect ones -- with no failing test.

test_verify_password_argument_order is the guard against that returning.
"""
from __future__ import annotations

import pytest

from app.core.security import (
    MIN_PASSWORD_LENGTH,
    hash_password,
    needs_rehash,
    password_meets_policy,
    verify_password,
)


def test_hash_then_verify_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_argument_order():
    """(plain, hashed) -- not (hashed, plain).

    The historical bug was an import-time redefinition with the parameters
    swapped. Called the other way round, verify_password would compare the
    hash string against itself and return False for every real password, which
    is what this asserts against.
    """
    plain = "s3cret-Passphrase"
    hashed = hash_password(plain)

    assert verify_password(plain, hashed) is True
    # Reversed order must fail, and must not raise.
    assert verify_password(hashed, plain) is False


def test_wrong_password_is_rejected():
    hashed = hash_password("right password here")
    assert verify_password("wrong password here", hashed) is False


def test_hash_is_salted_so_two_hashes_of_the_same_password_differ():
    a = hash_password("same password")
    b = hash_password("same password")
    assert a != b
    assert verify_password("same password", a) is True
    assert verify_password("same password", b) is True


def test_hash_does_not_contain_the_plaintext():
    plain = "do-not-leak-this-value"
    hashed = hash_password(plain)
    assert plain not in hashed


def test_empty_inputs_are_rejected_without_raising():
    hashed = hash_password("something")
    assert verify_password("", hashed) is False
    assert verify_password("something", "") is False
    assert verify_password("", "") is False


def test_malformed_hash_returns_false_not_an_exception():
    """A corrupted or truncated column must not break a login endpoint."""
    assert verify_password("anything", "not-an-argon2-hash") is False
    assert verify_password("anything", "$argon2id$truncated") is False


def test_needs_rehash_is_true_for_a_malformed_hash():
    assert needs_rehash("garbage") is True


def test_password_policy_enforces_minimum_length():
    ok, msg = password_meets_policy("a" * (MIN_PASSWORD_LENGTH - 1))
    assert ok is False
    assert msg is not None

    ok, msg = password_meets_policy("a" * MIN_PASSWORD_LENGTH)
    assert ok is True
    assert msg is None

# END OF FILE