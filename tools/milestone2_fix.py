"""Milestone 2 fix: photo storage method + recompute error surfacing."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BE = ROOT / "backend"

# ============================================================
# FIX 1: punches.py — storage.put -> storage.save, warnings tuple
# ============================================================
punches = BE / "app" / "api" / "v1" / "punches.py"
s = punches.read_text(encoding="utf-8")

# 1a. storage.put -> storage.save
old_put = "        storage.put(key, photo_bytes)\n"
new_put = '        storage.save(key, photo_bytes, content_type="image/jpeg")\n'
if old_put not in s:
    raise SystemExit("FATAL: storage.put call not found")
s = s.replace(old_put, new_put, 1)
print("FIX 1a: storage.put -> storage.save")

# 1b. Return annotation tuple[Punch, bool] -> tuple[Punch, list[str]]
old_ann = ") -> tuple[Punch, bool]:\n"
new_ann = ") -> tuple[Punch, list[str]]:\n"
if old_ann not in s:
    raise SystemExit("FATAL: return annotation tuple[Punch, bool] not found")
s = s.replace(old_ann, new_ann, 1)
print("FIX 1b: return type annotation -> tuple[Punch, list[str]]")

# 1c. Idempotent retry: return existing, False -> return existing, []
old_idem = "        return existing, False\n"
new_idem = "        return existing, []\n"
if old_idem not in s:
    raise SystemExit("FATAL: 'return existing, False' not found")
s = s.replace(old_idem, new_idem, 1)
print("FIX 1c: idempotent retry returns []")

# 1d. Init warnings before try
old_try = (
    "    import sys as _sys\n"
    "    import traceback as _tb\n"
    "    try:\n"
)
new_try = (
    "    import sys as _sys\n"
    "    import traceback as _tb\n"
    "    warnings: list[str] = []\n"
    "    try:\n"
)
if old_try not in s:
    raise SystemExit("FATAL: _sys/_tb imports + try not found")
s = s.replace(old_try, new_try, 1)
print("FIX 1d: warnings list initialised before try")

# 1e. Except block: set warning, return warnings not True
old_except = (
    "    except Exception as e:\n"
    "        db.rollback()\n"
    '        print(f"[TRIGGER FAILED] {type(e).__name__}: {e}", file=_sys.stderr)\n'
    "        _tb.print_exc(file=_sys.stderr)\n"
    "    return punch, True\n"
)
new_except = (
    "    except Exception as e:\n"
    "        db.rollback()\n"
    '        warnings = ["attendance_recompute_failed"]\n'
    '        print(f"[TRIGGER FAILED] {type(e).__name__}: {e}", file=_sys.stderr)\n'
    "        _tb.print_exc(file=_sys.stderr)\n"
    "    return punch, warnings\n"
)
if old_except not in s:
    raise SystemExit("FATAL: except block + return punch, True not found")
s = s.replace(old_except, new_except, 1)
print("FIX 1e: except block sets warning; returns warnings list")

# 1f. submit_punch caller
old_caller = (
    "    punch, _ = _process_punch(db, device, None, payload, request_id, server_received_at, tenant.crypto, storage, scanner)\n"
    "    return _to_out(punch)\n"
)
new_caller = (
    "    punch, warnings = _process_punch(db, device, None, payload, request_id, server_received_at, tenant.crypto, storage, scanner)\n"
    "    out = _to_out(punch)\n"
    "    out.warnings = warnings\n"
    "    return out\n"
)
if old_caller not in s:
    raise SystemExit("FATAL: submit_punch caller block not found")
s = s.replace(old_caller, new_caller, 1)
print("FIX 1f: submit_punch caller propagates warnings")

# 1g. submit_punch_batch caller
old_batch = (
    "            punch, _ = _process_punch(db, device, None, p, request_id, server_received_at, tenant.crypto, storage, scanner)\n"
    "            if punch.status == 'rejected':\n"
    "                rejected += 1\n"
    "            else:\n"
    "                accepted += 1\n"
    "            results.append(PunchBatchItemOut(index=i, ok=True, punch=_to_out(punch), error=None))\n"
)
new_batch = (
    "            punch, warnings = _process_punch(db, device, None, p, request_id, server_received_at, tenant.crypto, storage, scanner)\n"
    "            if punch.status == 'rejected':\n"
    "                rejected += 1\n"
    "            else:\n"
    "                accepted += 1\n"
    "            item_out = _to_out(punch)\n"
    "            item_out.warnings = warnings\n"
    "            results.append(PunchBatchItemOut(index=i, ok=True, punch=item_out, error=None))\n"
)
if old_batch not in s:
    raise SystemExit("FATAL: submit_punch_batch caller block not found")
s = s.replace(old_batch, new_batch, 1)
print("FIX 1g: submit_punch_batch caller propagates warnings")

punches.write_text(s, encoding="utf-8")

# ============================================================
# FIX 2: punches_schemas.py — add warnings to PunchOut
# ============================================================
schemas = BE / "app" / "api" / "v1" / "punches_schemas.py"
s = schemas.read_text(encoding="utf-8")

# Anchor inside PunchOut class only
idx = s.find("class PunchOut(")
if idx < 0:
    raise SystemExit("FATAL: class PunchOut not found")
before = s[:idx]
after = s[idx:]

old_field = "    raw_payload: dict[str, Any]\n    created_at: datetime\n"
new_field = (
    "    raw_payload: dict[str, Any]\n"
    "    created_at: datetime\n"
    "    warnings: list[str] = []\n"
)
if old_field not in after:
    raise SystemExit("FATAL: PunchOut anchor raw_payload+created_at not found")
after = after.replace(old_field, new_field, 1)
schemas.write_text(before + after, encoding="utf-8")
print("FIX 2: PunchOut gains 'warnings: list[str] = []'")

# ============================================================
# FIX 3: test_punches.py — 2 regression tests
# ============================================================
test = BE / "tests" / "test_punches.py"
s = test.read_text(encoding="utf-8")

if "_TINY_JPEG_B64" in s:
    print("SKIP 3a: _TINY_JPEG_B64 already present")
else:
    const = '''
# Tiny valid JPEG (1x1 pixel) base64-encoded. Used in Milestone 2 regression
# test that previously failed with HTTP 500 because punches.py called
# storage.put() on a Storage class that only implements save/load/delete/
# exists/signed_url.
_TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
    "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAARCAABAAEDASIA"
    "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA"
    "/9oADAMBAAIQAxAAAAEf/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QA"
    "FBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAA"
    "AP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBAB"
    "AAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABD/xAAUEQEAAAAA"
    "AAAAAAAAAAAAAAAA/9oACAEDAQE/EH//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEC"
    "AQE/EH//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EH//2Q=="
)

'''
    # Insert after the last top-level import
    lines = s.split("\n")
    insert_at = 0
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.startswith("from ") or stripped.startswith("import "):
            insert_at = i + 1
        elif stripped and not stripped.startswith("#") and insert_at > 0:
            break
    lines.insert(insert_at, const)
    s = "\n".join(lines)
    print("FIX 3a: _TINY_JPEG_B64 constant added")

new_tests = '''

# ---------------------------------------------------------------------------
# Milestone 2 regression tests
# ---------------------------------------------------------------------------


def test_submit_punch_with_valid_photo_persists(api, db):
    """Punch with valid photo must persist and return photo_object_key.

    Regression: pre-fix, punches.py called storage.put() which does not exist
    on the Storage base class (only save/load/delete/exists/signed_url). Result
    was AttributeError -> HTTP 500 for every photo-bearing punch.
    """
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, raw = _mk_device(db, site.id)
    emp = _mk_employee(db, 'PHOTO-1', site_id=site.id)
    payload = _payload(emp.id, photo_base64=_TINY_JPEG_B64)
    r = _post(client, tenant.slug, raw, payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['photo_object_key'] is not None, body
    assert body['photo_object_key'].startswith('punches/')


def test_submit_punch_surfaces_recompute_warning(api, db):
    """When attendance recompute fails, punch must persist (201) and the
    response must carry 'attendance_recompute_failed' in warnings.

    Regression: pre-fix, _process_punch caught every recompute exception,
    rolled back, printed to stderr, returned (punch, True). The caller
    discarded the bool and returned 201 with no signal that attendance was
    not built. In production this silently dropped attendance days.
    """
    client, tenant = api
    site = _mk_branch_site(db)
    _dev, raw = _mk_device(db, site.id)
    emp = _mk_employee(db, 'RECOMP-1', site_id=site.id)
    r = _post(client, tenant.slug, raw, _payload(emp.id))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['id'] is not None
    assert body['employee_id'] == str(emp.id)
    assert 'warnings' in body, body
    assert 'attendance_recompute_failed' in body['warnings'], body['warnings']
'''
s = s.rstrip() + new_tests
test.write_text(s, encoding="utf-8")
print("FIX 3b: 2 regression tests appended")

print("\nMilestone 2 fix patch complete.")