from __future__ import annotations

from contextvars import ContextVar

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.config import get_settings

_tenant_key_ctx: ContextVar[bytes | None] = ContextVar("tenant_encryption_key", default=None)


def set_tenant_key(key: bytes) -> None:
    _tenant_key_ctx.set(key)


def clear_tenant_key() -> None:
    _tenant_key_ctx.set(None)


def get_tenant_key() -> bytes:
    key = _tenant_key_ctx.get()
    if key is None:
        raise RuntimeError("Tenant encryption key not set in context")
    return key


def seal_with_master(plaintext: str) -> str:
    fernet = Fernet(get_settings().master_encryption_key.encode("ascii"))
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def unseal_with_master(ciphertext: str) -> str:
    fernet = Fernet(get_settings().master_encryption_key.encode("ascii"))
    return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")


def new_tenant_key() -> bytes:
    return Fernet.generate_key()


class EncryptedString(TypeDecorator[str]):
    """Text column encrypted with the current tenant Fernet key.

    Values are stored in the database as URL-safe base64 ciphertext.
    The tenant key is set in a ContextVar before any query executes.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: object) -> str | None:
        if value is None:
            return None
        fernet = Fernet(get_tenant_key())
        return fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def process_result_value(self, value: str | None, dialect: object) -> str | None:
        if value is None:
            return None
        fernet = Fernet(get_tenant_key())
        try:
            return fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("Failed to decrypt a tenant column value") from exc