
"""Cross-thread crypto test.

The whole reason we moved away from EncryptedString is that a ContextVar
holding the encryption key is invisible in a FastAPI worker thread. This
test proves TenantCrypto is safe across that boundary:

  * Test 1: write an encrypted value from one thread, read it from a
    different thread, and confirm the plaintext round-trips.
  * Test 2: without a key, both encrypt() and decrypt() raise the clear
    CryptoKeyMissing error.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet

from app.core.crypto import CryptoKeyMissing, TenantCrypto


def test_encrypted_value_survives_thread_boundary() -> None:
    key = Fernet.generate_key()

    # Encrypt on thread A.
    def write_thread() -> str:
        crypto = TenantCrypto(key)
        return crypto.encrypt("very-secret-payload")  # type: ignore[return-value]

    with ThreadPoolExecutor(max_workers=1) as ex_a:
        ciphertext = ex_a.submit(write_thread).result()

    # Decrypt on thread B.
    def read_thread(ct: str) -> str:
        crypto = TenantCrypto(key)
        return crypto.decrypt(ct)  # type: ignore[return-value]

    with ThreadPoolExecutor(max_workers=1) as ex_b:
        plaintext = ex_b.submit(read_thread, ciphertext).result()

    assert plaintext == "very-secret-payload"


def test_crypto_key_missing_errors_are_clear() -> None:
    no_key = TenantCrypto(None)
    with pytest.raises(CryptoKeyMissing, match="no key"):
        no_key.encrypt("x")
    with pytest.raises(CryptoKeyMissing, match="no key"):
        no_key.decrypt("x")
