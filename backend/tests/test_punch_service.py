'''Pure-function tests for punch_service (Chapter 2A, A2/A3/A4/A6).'''
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest

from app.api.v1.punch_service import (
    canonical_payload_hash,
    classify_match,
    compute_timing_and_offset,
    decode_and_validate_photo,
    is_clock_gap,
    is_future_time,
    validate_raw_payload,
)
from app.core.errors import AppError

_JPEG = bytes.fromhex('ffd8ff') + b'fake-jpeg-content'
_PNG = bytes.fromhex('89504e470d0a1a0a') + b'fake-png-content'


def _punch(**kw):
    base = {'employee_id': 'emp-1', 'device_time': datetime(2024, 5, 1, 8, 0, tzinfo=timezone.utc), 'device_now_at_send': None, 'method': 'fingerprint', 'match_score': 95, 'liveness_passed': True, 'latitude': None, 'longitude': None}
    base.update(kw)
    return base


def test_hash_is_stable():
    h1 = canonical_payload_hash(_punch())
    h2 = canonical_payload_hash(_punch())
    assert h1 == h2
    assert len(h1) == 64


def test_hash_changes_on_different_employee():
    h1 = canonical_payload_hash(_punch())
    h2 = canonical_payload_hash(_punch(employee_id='emp-2'))
    assert h1 != h2


def test_hash_changes_on_different_time():
    t2 = datetime(2024, 5, 1, 8, 1, tzinfo=timezone.utc)
    h1 = canonical_payload_hash(_punch())
    h2 = canonical_payload_hash(_punch(device_time=t2))
    assert h1 != h2


def test_hash_ignores_client_punch_id_photo_raw_payload():
    base = _punch()
    h1 = canonical_payload_hash(base)
    with_extra = dict(base)
    with_extra['client_punch_id'] = 'ignored'
    with_extra['photo_base64'] = 'ignored'
    with_extra['raw_payload'] = {'ignored': True}
    assert canonical_payload_hash(with_extra) == h1


def test_timing_live_punch():
    dt = datetime(2024, 5, 1, 8, 0, tzinfo=timezone.utc)
    srv = datetime(2024, 5, 1, 8, 0, 1, tzinfo=timezone.utc)
    eff, off = compute_timing_and_offset(dt, None, srv)
    assert eff == srv
    assert off == -1000


def test_timing_batch_punch_offline():
    dt = datetime(2024, 5, 1, 8, 0, tzinfo=timezone.utc)
    dnow = datetime(2024, 5, 1, 10, 0, 5, tzinfo=timezone.utc)
    srv = datetime(2024, 5, 1, 10, 0, 5, tzinfo=timezone.utc)
    eff, off = compute_timing_and_offset(dt, dnow, srv)
    assert eff == dt
    assert off == 0


def test_timing_batch_punch_fast_clock():
    dt = datetime(2024, 5, 1, 8, 10, tzinfo=timezone.utc)
    dnow = datetime(2024, 5, 1, 8, 10, 0, tzinfo=timezone.utc)
    srv = datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
    eff, off = compute_timing_and_offset(dt, dnow, srv)
    assert off == 600000
    assert eff == datetime(2024, 5, 1, 8, 0, tzinfo=timezone.utc)


def test_photo_none_returns_none():
    assert decode_and_validate_photo(None, 300000) is None


def test_photo_valid_jpeg():
    b64 = base64.b64encode(_JPEG).decode('ascii')
    out = decode_and_validate_photo(b64, 300000)
    assert out == _JPEG


def test_photo_valid_png():
    b64 = base64.b64encode(_PNG).decode('ascii')
    out = decode_and_validate_photo(b64, 300000)
    assert out == _PNG


def test_photo_invalid_base64():
    try:
        decode_and_validate_photo('!!!not base64!!!', 300000)
        assert False, 'should raise'
    except AppError as e:
        assert e.code == 'photo_invalid'


def test_photo_wrong_magic():
    b64 = base64.b64encode(b'<html>not an image</html>').decode('ascii')
    try:
        decode_and_validate_photo(b64, 300000)
        assert False, 'should raise'
    except AppError as e:
        assert e.code == 'photo_invalid'


def test_photo_oversize():
    big = _JPEG + b'x' * 400000
    b64 = base64.b64encode(big).decode('ascii')
    try:
        decode_and_validate_photo(b64, 300000)
        assert False, 'should raise'
    except AppError as e:
        assert e.code == 'photo_invalid'


def test_raw_payload_ok():
    validate_raw_payload({'firmware': '1.0.0', 'nested': {'x': 1}}, 8192)


def test_raw_payload_template_key_rejected():
    try:
        validate_raw_payload({'nested': {'face_template': 'abc'}}, 8192)
        assert False, 'should raise'
    except AppError as e:
        assert e.code == 'biometric_template_not_allowed'


def test_raw_payload_template_key_case_insensitive():
    try:
        validate_raw_payload({'Embedding': [1, 2, 3]}, 8192)
        assert False, 'should raise'
    except AppError as e:
        assert e.code == 'biometric_template_not_allowed'


def test_raw_payload_oversize():
    try:
        validate_raw_payload({'blob': 'x' * 9000}, 8192)
        assert False, 'should raise'
    except AppError as e:
        assert e.code == 'raw_payload_too_large'


def test_future_time_flag():
    srv = datetime(2024, 5, 1, 8, 0, tzinfo=timezone.utc)
    assert is_future_time(srv + timedelta(seconds=400), srv) is True
    assert is_future_time(srv + timedelta(seconds=100), srv) is False


def test_clock_gap_flag():
    assert is_clock_gap(400000, 300) is True
    assert is_clock_gap(100000, 300) is False
    assert is_clock_gap(-400000, 300) is True


def test_classify_match_ok():
    assert classify_match(95, True, 60) == []


def test_classify_match_low_confidence():
    assert classify_match(40, True, 60) == ['low_confidence']


def test_classify_match_liveness_failed():
    assert classify_match(95, False, 60) == ['liveness_failed']


def test_classify_match_both():
    assert sorted(classify_match(40, False, 60)) == ['liveness_failed', 'low_confidence']

# END OF FILE
