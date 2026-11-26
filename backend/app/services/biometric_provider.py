"""The vendor seam for biometric matching.

There is no matching algorithm in this repository and there is deliberately
none written here. Comparing two minutiae templates or two face embeddings is a
trained model's job; a hand-written approximation would return plausible scores
and verify nobody. This module defines the interface a real SDK plugs into,
plus implementations for the two states that exist today: nothing configured,
and a deterministic fake for tests.

Why a protocol rather than a direct SDK call:

    Vendors differ in template format, score range and threshold convention.
    Suprema returns an integer match score where 0 means identical; DigitalPersona
    returns a 0-100 similarity; face APIs return cosine distance where lower is
    better. Putting those behind one interface means the punch pipeline never
    learns a vendor's convention, and swapping SDKs does not touch the clock-in
    path.

Why VersionMismatch is a raised error rather than a low score:

    Templates from different vendors, or from different versions of the same
    SDK, are not comparable. Dijkstra-style alignment of two ISO templates from
    unrelated extractors produces a number that looks like a score and means
    nothing -- typically either a near-random value or a consistent zero. If
    that number flows into match_score, the system records a verification
    attempt that never happened. Refusing is the only honest answer.

Why NullProvider raises rather than returning zero:

    A zero score would read as "did not match", which routes to low_confidence
    and looks like a failed verification. The truth is that no verification is
    possible. Those are different facts and an HR user resolving the exception
    needs to know which one they are looking at.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

# Matches the threshold already used by classify_match in punch_service: a score
# at or above this counts as verified, below it becomes low_confidence. Kept as
# a module constant so the number exists in one place rather than drifting
# between the pipeline and whatever SDK is installed.
MATCH_THRESHOLD = 60.0

# A template shorter than this cannot describe a finger or a face. The same
# floor TemplateCrypto enforces, restated here because a provider validates
# before encryption, not after.
MIN_TEMPLATE_BYTES = 16


class ProviderNotConfigured(RuntimeError):
    """No biometric SDK is installed or configured for this tenant.

    Distinct from a failed match. This means the capability is absent, not that
    the employee was rejected.
    """


class TemplateInvalid(ValueError):
    """The bytes supplied are not a template this provider can use.

    Most often an empty read, a truncated transfer, or an image where a
    template was expected. The local agent talks to the reader over USB and a
    half-completed read is a real occurrence, not a theoretical one.
    """


class VersionMismatch(ValueError):
    """The two templates were produced by different extractors or versions.

    Comparing them would yield a meaningless number. See the module docstring.
    """


@runtime_checkable
class BiometricProvider(Protocol):
    """What a vendor adapter must supply.

    `template_version` is stored alongside every enrolment and compared at
    verification time. It must change whenever the extractor changes in a way
    that makes old templates incomparable -- bumping the SDK's major version,
    switching minutiae formats, or changing face models.
    """

    name: str
    template_version: str

    def validate_template(self, raw: bytes) -> None:
        """Raise TemplateInvalid if this is not a usable template.

        Called at enrolment before encryption and at verification before
        matching. Cheap, must not do cryptography or I/O.
        """
        ...

    def match(self, probe: bytes, reference: bytes) -> float:
        """Similarity of two templates, 0.0 to 100.0 inclusive.

        Must raise VersionMismatch if the two cannot be compared. Must not
        return a value for incomparable input.
        """
        ...


class NullProvider:
    """Stands in when no SDK is installed.

    Every method raises. This is the honest state of the system until a reader
    and its SDK arrive, and making it an object rather than None means a
    deployment cannot silently fall through to "treated as matched".
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
    """Deterministic stand-in so the pipeline is testable without hardware.

    Deliberately NOT a similarity heuristic. A real comparison would have to
    model minutiae alignment, and a plausible-looking fake invites someone to
    ship it. Instead matching is byte equality: identical templates score 100,
    anything else scores 0.

    That makes it useless as a biometric -- and that is the point. It cannot
    accidentally pass as working verification, while still exercising every
    branch of the pipeline: the version check, the threshold comparison, the
    score write, the low_confidence path.

    Tests that need a middle score use FakeProvider(scores=...) to pin an
    explicit value rather than deriving one.
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
        return self._match_score if bytes(probe) == bytes(reference) else self._non_match_score


_current: BiometricProvider = NullProvider()


def get_provider() -> BiometricProvider:
    """The provider this process is configured with.

    Module-level rather than per-tenant for now: the reader SDK is installed on
    the server, not per subscriber. If a future deployment has different
    hardware per tenant, this becomes a lookup keyed on subscriber_id and the
    call sites do not change.
    """
    return _current


def set_provider(provider: BiometricProvider) -> None:
    """Install a provider. Called at startup by a vendor adapter, or by tests."""
    global _current
    _current = provider


def reset_provider() -> None:
    global _current
    _current = NullProvider()