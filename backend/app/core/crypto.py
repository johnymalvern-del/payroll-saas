
"""TenantCrypto - explicit encryption of sensitive columns.

Rationale: FastAPI runs sync `def` endpoints on anyio worker threads.
ContextVars set by dependencies are not visible inside those worker
threads, so a ContextVar-held key cannot be relied on when a service
encrypts or decrypts a column. The safe pattern is to pass the key (or
this small TenantCrypto wrapper) explicitly through the call chain.

Columns declared for encrypted content are plain TEXT columns in the
database. Callers encrypt before writing and decrypt after reading.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class CryptoKeyMissing(RuntimeError):
    """Raised when encrypt() or decrypt() is called with no key set."""


class TenantCrypto:
    """Wraps a Fernet key for one tenant. Safe to construct per request."""

    def __init__(self, key: bytes | None) -> None:
        if not key:
            self._fernet: Fernet | None = None
        else:
            self._fernet = Fernet(key)

    def encrypt(self, plaintext: str | None) -> str | None:
        if plaintext is None:
            return None
        if self._fernet is None:
            raise CryptoKeyMissing("TenantCrypto has no key; cannot encrypt")
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str | None) -> str | None:
        if ciphertext is None:
            return None
        if self._fernet is None:
            raise CryptoKeyMissing("TenantCrypto has no key; cannot decrypt")
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("Failed to decrypt a tenant column value") from exc
