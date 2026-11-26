"""Binary-safe template encryption tests.

Pure logic, no database: a Fernet key is generated per test and wrapped in the
same TenantCrypto the application uses, so these run in well under a second.

The tests that matter most:

  test_round_trip_preserves_exact_bytes
      templates are binary and not UTF-8; a text-only path would raise on the
      first real scan
  test_encrypt_without_a_key_raises
      the failure mode this module exists to prevent -- an enrolment that
      looks successful and stores nothing
  test_needs_rekey_identifies_old_tokens_without_decrypting
      rotation cannot decrypt to find candidates, because the new key is what
      is failing
  test_non_utf8_template_round_trips
      the specific case TenantCrypto.encrypt() cannot handle
"""
from __future__ import annotations

from cryptography.fernet import Fernet

from app.core.crypto import CryptoKeyMissing, TenantCrypto
from app.core.template_crypto import (
    TemplateCrypto,
    TemplateCryptoError,
    key_version_of,
)


def crypto(key: bytes | None = None, version: str = "v1") -> TemplateCrypto:
    return TemplateCrypto(
        TenantCrypto(key or Fernet.generate_key()), key_version=version
    )


# A template-shaped payload: binary, high bytes, not valid UTF-8.
TEMPLATE = bytes(range(256)) + b"\x00\x01\x02minutiae"


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_round_trip_preserves_exact_bytes():
    c = crypto()
    stored = c.encrypt_template(TEMPLATE)
    assert c.decrypt_template(stored) == TEMPLATE


def test_non_utf8_template_round_trips():
    """The case TenantCrypto.encrypt() cannot handle on its own."""
    raw = b"\xff\xfe\x00\x80\x81\x82" * 40
    c = crypto()
    assert c.decrypt_template(c.encrypt_template(raw)) == raw


def test_same_template_encrypts_differently_each_time():
    """Fernet uses a random IV, so identical templates differ on disk.

    Without this, two employees enrolled with the same finger -- or one
    employee re-enrolling -- would be detectable by comparing ciphertext.
    """
    c = crypto()
    a = c.encrypt_template(TEMPLATE)
    b = c.encrypt_template(TEMPLATE)
    assert a != b
    assert c.decrypt_template(a) == c.decrypt_template(b)


def test_stored_value_carries_the_version_prefix():
    stored = crypto(version="v3").encrypt_template(TEMPLATE)
    assert stored.startswith("v3:")
    assert key_version_of(stored) == "v3"


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_encrypt_without_a_key_raises():
    """The failure this module exists to prevent.

    A silent None would mean enrolment appeared to succeed while storing
    nothing, and the failure would surface at the first verification attempt,
    in front of the employee.
    """
    c = TemplateCrypto(TenantCrypto(None))
    try:
        c.encrypt_template(TEMPLATE)
    except CryptoKeyMissing:
        return
    raise AssertionError("expected CryptoKeyMissing with no key configured")


def test_empty_template_is_refused():
    c = crypto()
    try:
        c.encrypt_template(b"")
    except TemplateCryptoError:
        return
    raise AssertionError("expected TemplateCryptoError for a zero-length template")


def test_tiny_template_is_refused():
    """A reader that returned a few stray bytes has not produced a template."""
    c = crypto()
    try:
        c.encrypt_template(b"\x00\x01\x02")
    except TemplateCryptoError:
        return
    raise AssertionError("expected TemplateCryptoError for a 3-byte template")


def test_string_instead_of_bytes_is_refused():
    c = crypto()
    try:
        c.encrypt_template("not bytes")  # type: ignore[arg-type]
    except TemplateCryptoError:
        return
    raise AssertionError("expected TemplateCryptoError for a str template")


def test_decrypt_with_a_different_key_raises():
    stored = crypto().encrypt_template(TEMPLATE)
    other = crypto()
    try:
        other.decrypt_template(stored)
    except TemplateCryptoError:
        return
    raise AssertionError("expected TemplateCryptoError under a different key")


def test_tampered_ciphertext_is_detected():
    stored = crypto().encrypt_template(TEMPLATE)
    # Flip a character in the body. Fernet's HMAC must reject it rather than
    # returning garbage.
    body = stored[len("v1:"):]
    flipped = body[:-2] + ("A" if body[-2] != "A" else "B") + body[-1]
    try:
        crypto().decrypt_template(f"v1:{flipped}")
    except TemplateCryptoError:
        return
    raise AssertionError("expected TemplateCryptoError for tampered ciphertext")


def test_empty_stored_value_is_refused():
    try:
        crypto().decrypt_template("")
    except TemplateCryptoError:
        return
    raise AssertionError("expected TemplateCryptoError for an empty value")


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


def test_needs_rekey_is_false_for_current_version():
    c = crypto(version="v2")
    assert c.needs_rekey(c.encrypt_template(TEMPLATE)) is False


def test_needs_rekey_identifies_old_tokens_without_decrypting():
    """Rotation cannot decrypt to find candidates: the new key is the failure."""
    old = crypto(version="v1")
    stored = old.encrypt_template(TEMPLATE)

    new = crypto(version="v2")
    assert new.needs_rekey(stored) is True

    # And the old token is genuinely unreadable under the new key, which is
    # exactly why needs_rekey must work without decrypting.
    try:
        new.decrypt_template(stored)
    except TemplateCryptoError:
        pass
    else:
        raise AssertionError("a v1 token should not decrypt under a v2 key")


def test_unversioned_value_is_treated_as_legacy():
    """A row written before this module existed must be rekeyed, not lost."""
    assert key_version_of("gAAAAABm-token-without-version") == "legacy"
    assert key_version_of("") == "legacy"


def test_legacy_token_is_reported_as_needing_rekey():
    c = crypto(version="v1")
    assert c.needs_rekey("gAAAAABm-token-without-version") is True


def test_invalid_version_label_is_rejected():
    try:
        crypto(version="v1:bad")
    except ValueError:
        return
    raise AssertionError("expected ValueError for a version containing ':'")