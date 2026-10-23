"""Tests for username normalisation and validation (Model-C refinement #1).

Six rules covered:
  1. Trimmed and lowercased.
  2. Rejects empty.
  3. Rejects '@'.
  4. Phone-number separators collapsed.
  5. '00' international prefix becomes '+'.
  6. looks_like_email heuristic is correct on typical inputs.
"""
from __future__ import annotations

import pytest

from app.core.usernames import (
    looks_like_email,
    normalise_mobile,
    normalise_username,
)


def test_trimmed_and_lowercased() -> None:
    assert normalise_username("  Alice  ") == "alice"
    assert normalise_username("BOB") == "bob"


def test_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        normalise_username("")
    with pytest.raises(ValueError, match="empty"):
        normalise_username("   ")


def test_rejects_at_sign() -> None:
    with pytest.raises(ValueError, match="@"):
        normalise_username("alice@example.com")


def test_phone_separators_collapsed() -> None:
    assert normalise_username("082 123 4567") == "0821234567"
    assert normalise_username("082-123-4567") == "0821234567"
    assert normalise_username("+27 (82) 123.4567") == "+27821234567"


def test_double_zero_becomes_plus() -> None:
    assert normalise_mobile("0027821234567") == "+27821234567"


def test_email_heuristic() -> None:
    assert looks_like_email("alice@example.com")
    assert looks_like_email("a@b")
    assert not looks_like_email("alice")
    assert not looks_like_email("0821234567")
    assert not looks_like_email("@")
    assert not looks_like_email("")