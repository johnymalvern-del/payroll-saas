"""Binary-safe encryption for biometric templates.

TenantCrypto encrypts str, deliberately: every column it serves
(national_id_encrypted, bank_account_number_encrypted, mfa_secret_encrypted)
holds text. A biometric template is not text. An ISO/IEC 19794-2 minutiae
template is 200-1500 bytes of binary that is not valid UTF-8, so
template.decode("utf-8") raises UnicodeDecodeError on the first real scan.

This module wraps TenantCrypto rather than modifying it. TenantCrypto is used
by live columns and changing its contract to accept bytes would put every one
of those at risk for the benefit of one new caller.

Why base64 rather than a raw-bytes mode:

    Fernet is text-in, text-out. The alternative is a second cipher
    implementation written here, and a second cipher implementation is exactly
    the thing not to hand-roll. base64 expands a 1 KB template to ~1.4 KB and
    raises the ciphertext by the same proportion. That cost is irrelevant next
    to writing crypto by hand.

    The base64 happens INSIDE the encrypted envelope. Encoding outside would
    leave the ciphertext length visible as a multiple of 4, giving away the
    template's size class. Inside, all the attacker learns is a bucket.

Why a version prefix outside the envelope:

    Key rotation has a specific failure mode for templates that passwords do
    not have. If a tenant key is rotated without re-encrypting, every enrolment
    becomes permanently unreadable, and every affected employee must present
    in person to enrol again. That is not a bug you can fix afterwards.

    To re-encrypt you must be able to find the rows encrypted under the old
    key WITHOUT decrypting them, because decryption with the new key is what
    fails. A plaintext version tag ("v1:", "v2:") gives exactly that. It leaks
    only which key generation was used, which is not sensitive.

    Fernet's InvalidToken does not distinguish "wrong key" from "tampered
    data" -- it raises the same exception for both. The version tag means
    rotation never has to make that distinction: prefix != current version
    means rekey, and prefix == current version with a failure means corruption.

What this module does NOT do:

    It does not make collection lawful. Encrypting a template you were not
    permitted to collect produces a well-encrypted violation. The section 8
    approval gate lives in the API layer and this module cannot substitute for
    it.

    It does not protect against an attacker holding the master key. Envelope
    encryption protects backups, disk images and stolen database dumps. It does
    not protect against root on the host that holds the master key.
"""
from __future__ import annotations

import base64
import binascii

from app.core.crypto import CryptoKeyMissing, TenantCrypto

_VERSION_SEPARATOR = ":"
_LEGACY_VERSION = "legacy"

# A zero-length template is not a template. Refusing here rather than storing an
# encrypted empty string means a reader that returns nothing cannot produce an
# enrolment row that looks successful and verifies nobody.
_MIN_TEMPLATE_BYTES = 16


class TemplateCryptoError(RuntimeError):
    """A template could not be encrypted or decrypted."""


class TemplateCrypto:
    """Encrypts and decrypts biometric templates for one tenant.

    Construct per request from the tenant context, exactly as TenantCrypto is:

        TemplateCrypto(tenant.crypto, key_version="v1")

    key_version must match whatever the tenant's current key generation is
    recorded as. It is written into the ciphertext prefix so rotation can find
    affected rows without decrypting them.
    """

    def __init__(self, inner: TenantCrypto, key_version: str = "v1") -> None:
        if not key_version or _VERSION_SEPARATOR in key_version:
            raise ValueError(
                f"key_version must be a non-empty string without "
                f"{_VERSION_SEPARATOR!r}; got {key_version!r}"
            )
        self._inner = inner
        self._version = key_version

    @property
    def version(self) -> str:
        return self._version

    def encrypt_template(self, raw: bytes) -> str:
        """Encrypt a binary template and return a versioned token.

        Raises CryptoKeyMissing when no key is configured. That is deliberate
        and differs from TenantCrypto.encrypt(None), which returns None for an
        absent optional column. A template is never optional: a silent None
        here would mean enrolment appeared to succeed while storing nothing,
        and the failure would only surface at the first verification attempt,
        in front of the employee.
        """
        if not isinstance(raw, (bytes, bytearray)):
            raise TemplateCryptoError(
                f"template must be bytes, got {type(raw).__name__}"
            )
        if len(raw) < _MIN_TEMPLATE_BYTES:
            raise TemplateCryptoError(
                f"template is {len(raw)} bytes, below the {_MIN_TEMPLATE_BYTES}-byte "
                f"minimum; a reader that returned nothing cannot produce a "
                f"usable enrolment"
            )

        # base64 produces ASCII, which TenantCrypto can carry unchanged.
        encoded = base64.b64encode(bytes(raw)).decode("ascii")
        token = self._inner.encrypt(encoded)
        if token is None:
            raise CryptoKeyMissing("tenant crypto returned no ciphertext")
        return f"{self._version}{_VERSION_SEPARATOR}{token}"

    def decrypt_template(self, stored: str) -> bytes:
        """Decrypt a versioned token back to the original template bytes.

        The version prefix is not validated here -- a caller decrypting an
        old-version token with the current key will get TemplateCryptoError,
        and rotation should have used needs_rekey() to find those rows first
        rather than attempting this.
        """
        if not isinstance(stored, str) or not stored:
            raise TemplateCryptoError("stored template is empty or not a string")

        _, sep, token = stored.partition(_VERSION_SEPARATOR)
        if not sep:
            # Unversioned value. Treat as a legacy token and try to read it, so
            # a column written before this module existed is not silently lost.
            token = stored

        try:
            encoded = self._inner.decrypt(token)
        except RuntimeError as exc:
            raise TemplateCryptoError(
                "template could not be decrypted: the key is wrong for this "
                "token, or the stored data has been altered"
            ) from exc
        if encoded is None:
            raise TemplateCryptoError("decryption produced no value")

        try:
            return base64.b64decode(encoded.encode("ascii"), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise TemplateCryptoError(
                "decrypted payload is not valid base64; the stored value is "
                "corrupt"
            ) from exc

    def needs_rekey(self, stored: str) -> bool:
        """True when a stored token was encrypted under a different key version.

        Rotation calls this across the table, re-encrypts the rows that return
        True, and only then retires the old key. Without this the old key must
        be kept forever, which defeats the point of rotating it.
        """
        return key_version_of(stored) != self._version


def key_version_of(stored: str) -> str:
    """The key version a token was written under, without decrypting it.

    Unversioned values return "legacy" rather than raising: a pre-existing row
    is a row that needs rekeying, not an error to abort the migration on.
    """
    if not isinstance(stored, str) or not stored:
        return _LEGACY_VERSION
    prefix, sep, _ = stored.partition(_VERSION_SEPARATOR)
    if not sep:
        return _LEGACY_VERSION
    return prefix or _LEGACY_VERSION