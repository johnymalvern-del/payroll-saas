"""Face embedding provider tests.

The arithmetic is pinned exactly, because the score feeds a threshold and a
threshold feeds whether someone's time is questioned.

test_threshold_distance_lands_on_sixty is the one that matters: 0.6 Euclidean
distance must produce exactly the pipeline's threshold, or the existing
MATCH_THRESHOLD of 60 stops meaning what it meant.
"""
from __future__ import annotations

import struct

import pytest

from app.services.biometric_provider import (
    MATCH_THRESHOLD,
    TemplateInvalid,
    build_provider,
    reset_provider,
)
from app.services.face_provider import (
    EMBEDDING_BYTES,
    EMBEDDING_DIMS,
    FaceEmbeddingProvider,
)


def vec(*values, pad: float = 0.0) -> bytes:
    """A 128-float embedding from the given leading values."""
    vals = list(values) + [pad] * (EMBEDDING_DIMS - len(values))
    return struct.pack(f"<{EMBEDDING_DIMS}f", *vals)


def test_embedding_size_is_512_bytes():
    assert EMBEDDING_DIMS == 128
    assert EMBEDDING_BYTES == 512


def test_identical_embeddings_score_100():
    p = FaceEmbeddingProvider()
    assert p.match(vec(0.5, -0.2, 0.1), vec(0.5, -0.2, 0.1)) == 100.0


def test_threshold_distance_lands_on_sixty():
    """0.6 distance must be exactly the pipeline threshold.

    Constructed by putting all 0.6 of distance into one component.
    """
    p = FaceEmbeddingProvider()
    score = p.match(vec(0.0), vec(0.6))
    assert score == pytest.approx(MATCH_THRESHOLD, abs=0.01)


def test_distance_above_threshold_scores_below_it():
    p = FaceEmbeddingProvider()
    assert p.match(vec(0.0), vec(0.7)) < MATCH_THRESHOLD


def test_distance_below_threshold_scores_above_it():
    p = FaceEmbeddingProvider()
    assert p.match(vec(0.0), vec(0.5)) > MATCH_THRESHOLD


def test_score_never_goes_negative():
    p = FaceEmbeddingProvider()
    assert p.match(vec(0.0), vec(5.0)) == 0.0


def test_validate_accepts_a_well_formed_embedding():
    FaceEmbeddingProvider().validate_template(vec(0.1, 0.2))


def test_wrong_length_is_refused():
    with pytest.raises(TemplateInvalid):
        FaceEmbeddingProvider().validate_template(b"\x00" * 100)


def test_all_zero_embedding_is_refused():
    """A failed detection yields zeros; storing it would match everything."""
    with pytest.raises(TemplateInvalid):
        FaceEmbeddingProvider().validate_template(vec())


def test_nan_is_refused():
    with pytest.raises(TemplateInvalid):
        FaceEmbeddingProvider().validate_template(vec(float("nan"), 0.1))


def test_string_is_refused():
    with pytest.raises(TemplateInvalid):
        FaceEmbeddingProvider().validate_template("not bytes")  # type: ignore[arg-type]


def test_build_provider_selects_face():
    assert isinstance(build_provider("face"), FaceEmbeddingProvider)


def test_build_provider_selects_null_by_default():
    assert build_provider(None).name == "null"
    assert build_provider("").name == "null"


def test_build_provider_rejects_unknown_name():
    from app.services.biometric_provider import ProviderNotConfigured

    with pytest.raises(ProviderNotConfigured):
        build_provider("retina-scan")


def test_get_provider_reads_the_environment(monkeypatch):
    from app.services.biometric_provider import get_provider

    monkeypatch.setenv("BIOMETRIC_PROVIDER", "face")
    reset_provider()
    try:
        assert isinstance(get_provider(), FaceEmbeddingProvider)
    finally:
        reset_provider()