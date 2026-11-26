"""Provider seam tests.

No database, no encryption: these pin the contract that a vendor adapter must
satisfy and the behaviour of the two implementations that exist today.

The tests that matter most:

  test_null_provider_raises_rather_than_returning_zero
      a zero would read as "did not match", route to low_confidence, and look
      like a failed verification when the truth is that no verification was
      possible
  test_fake_provider_is_exact_match_only
      the fake must not be mistakable for a working matcher
  test_match_threshold_matches_punch_pipeline
      the number lives in one place; if the pipeline's threshold moves, this
      fails rather than letting the two drift silently
"""
from __future__ import annotations

import pytest

from app.services.biometric_provider import (
    MATCH_THRESHOLD,
    MIN_TEMPLATE_BYTES,
    BiometricProvider,
    FakeProvider,
    NullProvider,
    ProviderNotConfigured,
    TemplateInvalid,
    get_provider,
    reset_provider,
    set_provider,
)

TEMPLATE = bytes(range(64))
OTHER = bytes(range(1, 65))


def test_null_provider_satisfies_the_protocol():
    assert isinstance(NullProvider(), BiometricProvider)


def test_fake_provider_satisfies_the_protocol():
    assert isinstance(FakeProvider(), BiometricProvider)


def test_null_provider_raises_rather_than_returning_zero():
    # A zero would read as "did not match", which routes to low_confidence and
    # looks like a failed verification. The truth is that no verification was
    # possible, and an HR user needs to know which it is.
    p = NullProvider()
    with pytest.raises(ProviderNotConfigured):
        p.match(TEMPLATE, TEMPLATE)


def test_null_provider_refuses_to_validate():
    with pytest.raises(ProviderNotConfigured):
        NullProvider().validate_template(TEMPLATE)


def test_default_provider_is_null():
    reset_provider()
    assert isinstance(get_provider(), NullProvider)


def test_set_provider_installs_and_reset_restores():
    fake = FakeProvider()
    set_provider(fake)
    assert get_provider() is fake
    reset_provider()
    assert isinstance(get_provider(), NullProvider)


def test_fake_provider_scores_identical_templates_high():
    p = FakeProvider()
    assert p.match(TEMPLATE, TEMPLATE) == 100.0


def test_fake_provider_scores_different_templates_low():
    p = FakeProvider()
    assert p.match(TEMPLATE, OTHER) == 0.0


def test_fake_provider_is_exact_match_only():
    """A one-byte difference must not score near 100.

    Behavioural pin: if someone later replaces the body with a similarity
    heuristic to make tests "more realistic", this fails.
    """
    almost = TEMPLATE[:-1] + bytes([TEMPLATE[-1] ^ 0xFF])
    assert FakeProvider().match(TEMPLATE, almost) == 0.0


def test_fake_provider_scores_are_explicitly_configurable():
    p = FakeProvider(match_score=42.0, non_match_score=7.5)
    assert p.match(TEMPLATE, TEMPLATE) == 42.0
    assert p.match(TEMPLATE, OTHER) == 7.5


def test_fake_provider_rejects_short_template():
    with pytest.raises(TemplateInvalid):
        FakeProvider().validate_template(b"\x00\x01")


def test_fake_provider_rejects_str():
    with pytest.raises(TemplateInvalid):
        FakeProvider().validate_template("not bytes")  # type: ignore[arg-type]


def test_fake_provider_rejects_short_template_on_match():
    with pytest.raises(TemplateInvalid):
        FakeProvider().match(b"\x00", TEMPLATE)


def test_template_version_is_reported():
    assert FakeProvider().template_version == "fake-v1"
    assert FakeProvider(template_version="fake-v2").template_version == "fake-v2"


def test_match_threshold_matches_punch_pipeline():
    """classify_match in punch_service uses 60.0. One number, one place."""
    assert MATCH_THRESHOLD == 60.0


def test_minimum_template_size_is_meaningful():
    assert MIN_TEMPLATE_BYTES >= 16
    assert len(TEMPLATE) >= MIN_TEMPLATE_BYTES