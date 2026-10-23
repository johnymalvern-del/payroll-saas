
"""Master-key encryption utilities.

This module holds only the master-key sealing helpers used by tenant
provisioning and the control database. Per-tenant encryption of application
columns is now handled by TenantCrypto in app/core/crypto.py; there is no
ContextVar-held key and no SQLAlchemy TypeDecorator for encrypted columns.
Columns whose contents must be encrypted are declared as plain Text; the
calling code encrypts before writing and decrypts after reading.
"""
from __future__ import annotations

from cryptography.fernet import Fernet

from app.core.config import get_settings


def seal_with_master(plaintext: str) -> str:
    fernet = Fernet(get_settings().master_encryption_key.encode("ascii"))
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def unseal_with_master(ciphertext: str) -> str:
    fernet = Fernet(get_settings().master_encryption_key.encode("ascii"))
    return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")


def new_tenant_key() -> bytes:
    return Fernet.generate_key()
