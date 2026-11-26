"""Face embedding provider: 128-d descriptors compared by Euclidean distance.

This is real matching, not a stand-in. A face model (face-api.js, running in
the browser) converts an image into a 128-float vector. Compare two vectors and
the distance tells you whether they are the same face. The model is the hard
part and it already exists; the comparison is arithmetic, which is why this
module is short.

What this is NOT:

    It is not liveness detection. A photograph of a face produces a valid
    embedding and will match. That is a genuine limitation and the reason the
    policy treats a match as "verified, subject to review" rather than as proof
    of physical presence. Commercial SDKs sell liveness detection separately
    and it is the expensive part.

    It is not as accurate as a dedicated face SDK. It is good enough to make
    sharing a PIN harder, which is a real improvement over no verification at
    all.

Score mapping, chosen so the existing threshold applies unchanged:

    face-api.js treats Euclidean distance below 0.6 as the same person --
    typically 0.2-0.4 for a genuine match, 0.8-1.2 for different people.

    score = 100 * (1 - distance / 1.5), clamped to 0..100

    distance 0.0 -> 100
    distance 0.6 ->  60   <- exactly MATCH_THRESHOLD
    distance 1.5 ->   0

    Anchoring the threshold on 0.6 rather than inventing a new number means
    the punch pipeline, the exception routing and the provider interface all
    keep working without adjustment.
"""
from __future__ import annotations

import math
import struct

from app.services.biometric_provider import TemplateInvalid

EMBEDDING_DIMS = 128
EMBEDDING_BYTES = EMBEDDING_DIMS * 4  # float32 per component

# Maps raw distance onto 0-100 so that 0.6 distance lands on 60.0, the
# threshold classify_match and MATCH_THRESHOLD already use.
_DISTANCE_AT_ZERO_SCORE = 1.5


class FaceEmbeddingProvider:
    """Compares face-api.js 128-d descriptors."""

    name = "face-embedding"
    template_version = "face-api-128-v1"

    def validate_template(self, raw: bytes) -> None:
        if not isinstance(raw, (bytes, bytearray)):
            raise TemplateInvalid(
                f"embedding must be bytes, got {type(raw).__name__}"
            )
        if len(raw) != EMBEDDING_BYTES:
            raise TemplateInvalid(
                f"embedding is {len(raw)} bytes; a {EMBEDDING_DIMS}-dimension "
                f"float32 descriptor is exactly {EMBEDDING_BYTES} bytes"
            )
        values = struct.unpack(f"<{EMBEDDING_DIMS}f", bytes(raw))
        if not all(math.isfinite(v) for v in values):
            raise TemplateInvalid("embedding contains NaN or infinity")

        # An all-zero vector is what a failed detection produces if it is not
        # checked. Storing it would create an enrolment that matches every
        # other all-zero probe -- a silent universal key.
        if all(v == 0.0 for v in values):
            raise TemplateInvalid(
                "embedding is all zeros; the face detector returned nothing"
            )

    def match(self, probe: bytes, reference: bytes) -> float:
        self.validate_template(probe)
        self.validate_template(reference)

        p = struct.unpack(f"<{EMBEDDING_DIMS}f", bytes(probe))
        r = struct.unpack(f"<{EMBEDDING_DIMS}f", bytes(reference))

        distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(p, r)))
        score = 100.0 * (1.0 - distance / _DISTANCE_AT_ZERO_SCORE)
        return max(0.0, min(100.0, score))