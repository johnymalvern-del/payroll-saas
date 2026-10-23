"""Username normalisation and validation (Model C refinement #1).

Rules:
  * Stored lowercase, whitespace trimmed at both ends.
  * May not contain '@' - reserved for email addresses.
  * May not be empty.
  * When a mobile number is used, separators are stripped and a leading
    '00' becomes '+'. Local numbers are left local - no country code added.
"""
from __future__ import annotations

_MOBILE_SEPARATORS = str.maketrans("", "", " -()./")


def normalise_mobile(raw: str) -> str:
    cleaned = raw.translate(_MOBILE_SEPARATORS)
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    return cleaned


def normalise_username(raw: str) -> str:
    if not isinstance(raw, str):
        raise ValueError("username must be a string")
    stripped = raw.strip()
    if not stripped:
        raise ValueError("username may not be empty")
    if "@" in stripped:
        raise ValueError("username may not contain '@' (reserved for email)")
    if any(c.isdigit() for c in stripped) and any(c in " -()./" for c in stripped):
        stripped = normalise_mobile(stripped)
    return stripped.lower()


def looks_like_email(raw: str) -> bool:
    if not isinstance(raw, str):
        return False
    stripped = raw.strip()
    if "@" not in stripped:
        return False
    local, _, domain = stripped.partition("@")
    return bool(local) and bool(domain)