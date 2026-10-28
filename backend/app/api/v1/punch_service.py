'''Punch processing helpers (Chapter 2A, pure functions).

No database, no HTTP. Every function takes plain values and returns
plain values or raises AppError. This is what makes A2/A3/A6 testable
without spinning up a tenant.

A2 timing: 
    offset_ms = device_now_at_send - server_received_at  (batch) 
    offset_ms = device_time - server_received_at         (live, device_now absent)
    effective_time = device_time - offset_ms
So a live punch always resolves to effective_time == server_received_at;
a batch preserves the original wall-clock time even when the device
clock is off.
'''
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.core.errors import AppError


def canonical_payload_hash(punch: dict[str, Any]) -> str:
    '''SHA-256 hex of the canonical identity fields of a punch.

    Excludes client_punch_id (that IS the idempotency key), photo_base64
    (large and device-specific), and raw_payload (device-specific noise).
    Includes the fields that make a punch 'the same punch' for A3's
    same-UUID-same-payload rule.
    '''
    fields = {
        'employee_id': str(punch.get('employee_id', '')),
        'device_time': punch.get('device_time').isoformat() if punch.get('device_time') else None,
        'device_now_at_send': punch.get('device_now_at_send').isoformat() if punch.get('device_now_at_send') else None,
        'method': punch.get('method'),
        'match_score': str(punch.get('match_score')) if punch.get('match_score') is not None else None,
        'liveness_passed': punch.get('liveness_passed'),
        'latitude': str(punch.get('latitude')) if punch.get('latitude') is not None else None,
        'longitude': str(punch.get('longitude')) if punch.get('longitude') is not None else None,
    }
    canonical = json.dumps(fields, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def compute_timing_and_offset(
    device_time: datetime,
    device_now_at_send: datetime | None,
    server_received_at: datetime,
) -> tuple[datetime, int]:
    '''Return (effective_time, offset_ms). A2.

    Live punch (device_now_at_send is None): offset = device_time - server_received_at,
    effective_time = device_time - offset = server_received_at.

    Batch punch (device_now_at_send present): offset = device_now - server_received_at,
    effective_time = device_time - offset.
    '''
    if device_now_at_send is not None:
        offset_ms = int((device_now_at_send - server_received_at).total_seconds() * 1000)
    else:
        offset_ms = int((device_time - server_received_at).total_seconds() * 1000)
    effective_time = device_time - __import__('datetime').timedelta(milliseconds=offset_ms)
    return effective_time, offset_ms


def decode_and_validate_photo(photo_base64: str | None, max_bytes: int) -> bytes | None:
    '''Base64-decode and JPEG/PNG-magic-check a photo. A6.

    Returns the decoded bytes on success, or None if photo_base64 is None.
    Raises AppError('photo_invalid', ...) on bad base64, unknown format,
    or oversize. The caller stores the bytes via StorageDep and records
    the returned object key.
    '''
    if photo_base64 is None:
        return None
    try:
        decoded = base64.b64decode(photo_base64, validate=True)
    except (binascii.Error, ValueError):
        raise AppError('photo_invalid', 'photo_base64 is not valid base64', 400)
    if len(decoded) > max_bytes:
        raise AppError('photo_invalid', f'photo exceeds {max_bytes} bytes', 400, {'size': len(decoded)})
    if decoded.startswith(bytes.fromhex('ffd8ff')):
        return decoded
    if decoded.startswith(bytes.fromhex('89504e470d0a1a0a')):
        return decoded
    raise AppError('photo_invalid', 'photo must be JPEG or PNG', 400)


_TEMPLATE_KEYS = frozenset({'template', 'fingerprint_template', 'face_template', 'embedding'})


def validate_raw_payload(raw_payload: dict[str, Any], max_bytes: int) -> None:
    '''Reject biometric-shaped keys and oversize payloads. A6.'''
    def _walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and k.lower() in _TEMPLATE_KEYS:
                    raise AppError('biometric_template_not_allowed', f'raw_payload contains a template-shaped key at {path}.{k}', 422)
                _walk(v, f'{path}.{k}')
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _walk(v, f'{path}[{i}]')
    _walk(raw_payload, 'payload')
    serialized = json.dumps(raw_payload, separators=(',', ':'))
    if len(serialized.encode('utf-8')) > max_bytes:
        raise AppError('raw_payload_too_large', f'raw_payload exceeds {max_bytes} bytes', 422)


def is_future_time(effective_time: datetime, server_received_at: datetime, tolerance_seconds: int = 300) -> bool:
    '''A2: effective_time more than 5 minutes after server_received_at.'''
    delta = (effective_time - server_received_at).total_seconds()
    return delta > tolerance_seconds


def is_clock_gap(offset_ms: int, threshold_seconds: int) -> bool:
    '''A2: abs(offset_ms) exceeds the configured clock-gap threshold.'''
    return abs(offset_ms) > threshold_seconds * 1000


def classify_match(match_score, liveness_passed, confidence_threshold: float) -> list[str]:
    '''A4: return ['low_confidence'] and/or ['liveness_failed'] based on inputs.'''
    flags: list[str] = []
    if match_score is not None and float(match_score) < confidence_threshold:
        flags.append('low_confidence')
    if liveness_passed is False:
        flags.append('liveness_failed')
    return flags

# END OF FILE
