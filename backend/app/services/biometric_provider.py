"""The vendor seam for biometric matching.

No matching algorithm is written from scratch here. Face comparison is done by
face_provider (a real embedding model, real arithmetic); fingerprint comparison
requires a reader SDK and remains unimplemented until hardware exists.

Why a protocol rather than a direct SDK call:

    Vendors differ in template format, score range and threshold convention.
    Putting them behind one interface means the punch pipeline never learns a
    vendor's convention, and swapping SDKs does not touch clock-in.

Why VersionMismatch is a raised error rather than a low score:

    Templates from different extractors are not comparable. Comparing them
    yields a number that looks like a score and means nothing. If that number
    reached match_score, the system would record a verification that never
    happened.

Why the provider is configured lazily from the environment:

    Configuring at import time would run before the app has read its settings,
    and would make every test import order-dependent. get_provider() configures
    once, on first call, from BIOMETRIC_PROVIDER.

    BIOMETRIC_PROVIDER=fake    for tests and demos -- byte equality only
    BIOMETRIC_PROVIDER=face    real face-embedding comparison
    unset / null               no provider; every biometric punch reports
                               UNAVAILABLE rather than pretending to verify
"""
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

MATCH_THRESHOLD = 60.0
MIN_TEMPLATE_BYTES = 16


class ProviderNotConfigured(RuntimeError):
    """No biometric SDK is installed or configured."""


class TemplateInvalid(ValueError):
    """The bytes supplied are not a template this provider can use."""


class VersionMismatch(ValueError):
    """The two templates were produced by different extractors or versions."""


@runtime_checkable
class BiometricProvider(Protocol):
    name: str
    template_version: str

    def validate_template(self, raw: bytes) -> None: ...

    def match(self, probe: bytes, reference: bytes) -> float: ...


class NullProvider:
    """Stands in when no SDK is installed. Every method raises.

    An object rather than None so a deployment cannot silently fall through to
    "treated as matched".
    """

    name = "null"
    template_version = "none"

    def validate_template(self, raw: bytes) -> None:
        raise ProviderNotConfigured(
            "no biometric provider is configured; enrol a reader SDK before "
            "attempting verification"
        )

    def match(self, probe: bytes, reference: bytes) -> float:
        raise ProviderNotConfigured(
            "no biometric provider is configured; cannot verify a template"
        )


class FakeProvider:
    """Deterministic stand-in for tests. Byte equality, nothing cleverer.

    Deliberately NOT a similarity heuristic. A plausible-looking fake invites
    someone to ship it. Equality scores 100, anything else 0 -- useless as a
    biometric, and therefore impossible to mistake for working verification,
    while still exercising every branch of the pipeline.
    """

    name = "fake"
    template_version = "fake-v1"

    def __init__(
        self,
        *,
        template_version: str = "fake-v1",
        match_score: float = 100.0,
        non_match_score: float = 0.0,
    ) -> None:
        self.template_version = template_version
        self._match_score = match_score
        self._non_match_score = non_match_score

    def validate_template(self, raw: bytes) -> None:
        if not isinstance(raw, (bytes, bytearray)):
            raise TemplateInvalid(
                f"template must be bytes, got {type(raw).__name__}"
            )
        if len(raw) < MIN_TEMPLATE_BYTES:
            raise TemplateInvalid(
                f"template is {len(raw)} bytes, below the "
                f"{MIN_TEMPLATE_BYTES}-byte minimum"
            )

    def match(self, probe: bytes, reference: bytes) -> float:
        self.validate_template(probe)
        self.validate_template(reference)
        return (
            self._match_score
            if bytes(probe) == bytes(reference)
            else self._non_match_score
        )


_current: BiometricProvider | None = None


def build_provider(name: str | None) -> BiometricProvider:
    """Construct a provider from its configuration name.

    The face provider is imported inside the function: it imports
    TemplateInvalid from this module, so a module-level import would be
    circular.
    """
    kind = (name or "").strip().lower()
    if kind in ("", "null", "none"):
        return NullProvider()
    if kind == "fake":
        return FakeProvider()
    if kind in ("face", "face-embedding"):
        from app.services.face_provider import FaceEmbeddingProvider

        return FaceEmbeddingProvider()
    raise ProviderNotConfigured(
        f"BIOMETRIC_PROVIDER={name!r} is not recognised; expected "
        f"'face', 'fake' or unset"
    )


def get_provider() -> BiometricProvider:
    """The provider this process is configured with, resolved once."""
    global _current
    if _current is None:
        _current = build_provider(os.environ.get("BIOMETRIC_PROVIDER"))
    return _current


def set_provider(provider: BiometricProvider) -> None:
    global _current
    _current = provider


def reset_provider() -> None:
    global _current
    _current = None