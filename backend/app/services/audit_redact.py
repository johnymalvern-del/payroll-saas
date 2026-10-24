
"""Redaction helper for audit-log values.

Every create, update or deactivate writes an audit_log row with old_value and
new_value. Sensitive fields must never appear there in plaintext. This module
centralises the redaction so every write path uses the same rule.

Sensitive keys are matched case-insensitively. The list is:

    national_id, national_id_encrypted
    bank_account_number, bank_account_number_encrypted
    mfa_secret, mfa_secret_encrypted
    password, password_hash, current_password, new_password
    token, access_token, refresh_token, jti, jti_hash

Nested dicts and lists are walked recursively. Nothing else is redacted:
tax_number, paye_reference, uif_reference, sdl_reference, coida_reference,
email, mobile, first_name, last_name all remain because they are either
business identifiers or already-excluded-not-secret identity fields, and a
post-hoc audit investigation needs to see them.
"""
from __future__ import annotations

from typing import Any


REDACTED = "[redacted]"

_SENSITIVE_KEYS: frozenset[str] = frozenset({
    "national_id",
    "national_id_encrypted",
    "bank_account_number",
    "bank_account_number_encrypted",
    "mfa_secret",
    "mfa_secret_encrypted",
    "password",
    "password_hash",
    "current_password",
    "new_password",
    "token",
    "access_token",
    "refresh_token",
    "jti",
    "jti_hash",
})


def _is_sensitive(key: str) -> bool:
    return key.lower() in _SENSITIVE_KEYS


def redact_for_audit(value: Any) -> Any:
    """Return a redacted copy of value (dict, list, or scalar)."""
    if value is None:
        return None
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and _is_sensitive(k):
                out[k] = REDACTED
            else:
                out[k] = redact_for_audit(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact_for_audit(v) for v in value]
    return value
