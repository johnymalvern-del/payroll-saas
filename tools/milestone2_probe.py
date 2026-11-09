"""Milestone 2 investigation probe. Read-only + one in-process reproduction."""
import inspect
import sys
import traceback
from pathlib import Path

BE = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BE))


def head(path, marker, before=5, after=60):
    p = Path(path)
    if not p.exists():
        print(f"--- {path} NOT FOUND ---")
        return
    lines = p.read_text(encoding="utf-8").split("\n")
    for i, ln in enumerate(lines):
        if marker in ln:
            lo = max(0, i - before)
            hi = min(len(lines), i + after)
            print(f"--- {path} around line {i+1} ---")
            for j in range(lo, hi):
                mark = ">>" if j == i else "  "
                print(f"{mark} {j+1:4}: {lines[j]}")
            print()
            return
    print(f"--- {path}: marker {marker!r} not found ---")


# ============================================================
print("=" * 60)
print("SECTION 1 — POST /punches endpoint handler")
print("=" * 60)
head(BE / "app" / "api" / "v1" / "punches.py", "def submit_punch", before=15, after=80)

# ============================================================
print("=" * 60)
print("SECTION 2 — decode_and_validate_photo + storage write in punch_service")
print("=" * 60)
head(BE / "app" / "api" / "v1" / "punch_service.py", "def decode_and_validate_photo", before=3, after=40)
head(BE / "app" / "api" / "v1" / "punch_service.py", "photo_object_key", before=3, after=25)

# ============================================================
print("=" * 60)
print("SECTION 3 — StorageDep and _storage")
print("=" * 60)
head(BE / "app" / "api" / "deps.py", "def _storage", before=3, after=30)
head(BE / "app" / "api" / "deps.py", "StorageDep", before=1, after=3)

# ============================================================
print("=" * 60)
print("SECTION 4 — Storage class")
print("=" * 60)
# Find the Storage class
import importlib
try:
    from app.core import storage as st_mod
    print(f"Storage module: {st_mod.__file__}")
    print(inspect.getsource(st_mod))
except Exception as e:
    print(f"app.core.storage not found: {e}")
    # Try alternate paths
    for cand in ("app.services.storage", "app.core.storage_dep", "app.storage"):
        try:
            mod = importlib.import_module(cand)
            print(f"Found: {cand} -> {mod.__file__}")
            print(inspect.getsource(mod)[:3000])
            break
        except ImportError:
            pass

# ============================================================
print("=" * 60)
print("SECTION 5 — config: storage settings")
print("=" * 60)
from app.core.config import get_settings
try:
    settings = get_settings()
    storage_attrs = [
        a for a in dir(settings)
        if "storage" in a.lower() or "upload" in a.lower()
        or "s3" in a.lower() or "media" in a.lower() or "photo" in a.lower()
    ]
    print(f"storage-related settings: {storage_attrs}")
    for a in storage_attrs:
        try:
            print(f"  {a} = {getattr(settings, a)!r}")
        except Exception as e:
            print(f"  {a} = <error: {e}>")
except Exception as e:
    print(f"settings load failed: {e}")

# ============================================================
print("=" * 60)
print("SECTION 6 — recompute error handling in punches.py")
print("=" * 60)
punches_src = (BE / "app" / "api" / "v1" / "punches.py").read_text(encoding="utf-8")
lines = punches_src.split("\n")
for i, ln in enumerate(lines, 1):
    if "recompute" in ln.lower() or "try:" in ln or "except" in ln:
        print(f"{i:4}: {ln}")

# ============================================================
print("=" * 60)
print("SECTION 7 — REPRODUCE THE 500 (in-process, direct storage.write)")
print("=" * 60)
import base64
# Tiny valid 1x1 JPEG
TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00"
    b"\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\x09"
    b"\x09\x08\x0a\x0c\x14\x0d\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d"
    b"\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0"
    b"\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00"
    b"\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01"
    b"\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\xff\xc4\x00\xb5\x10\x00\x02"
    b"\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03"
    b"\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07\"q\x142\x81\x91\xa1\x08#B"
    b"\xb1\xc1\x15R\xd1\xf0$3br\x82\x09\x0a\x16\x17\x18\x19\x1a%&'()*4567"
    b"\x89:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\xc4\x00\xb5\x11\x00\x02\x01\x02"
    b"\x04\x04\x03\x04\x07\x05\x04\x04\x00\x01\x02w\x00\x01\x02\x03\x11\x04"
    b"\x05!1\x06\x12AQ\x07aq\x13\"2\x81\x08\x14B\x91\xa1\xb1\xc1\x09#3R\xf0"
    b"\x15br\xd1\x0a\x16$4\xe1%\xf1\x17\x18\x19\x1a&'()*56789:CDEFGHIJSTUVWXYZcdefghij"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xd2\xcf \xff\xd9"
)
photo_b64 = base64.b64encode(TINY_JPEG).decode("ascii")

print(f"photo_b64 length: {len(photo_b64)}")

# Try decode_and_validate_photo first
try:
    from app.api.v1.punch_service import decode_and_validate_photo
    result = decode_and_validate_photo(photo_b64, 10 * 1024 * 1024)
    print(f"decode_and_validate_photo OK, returned {len(result) if result else 0} bytes")
except Exception as e:
    print(f"decode_and_validate_photo RAISED: {type(e).__name__}: {e}")
    traceback.print_exc()

# Now try to construct Storage and write
print()
print(">>> Attempting storage write directly (this is where the 500 likely comes from)")
try:
    from app.api.deps import _storage
    storage = _storage()
    print(f"storage instance: {type(storage)}")
    print(f"storage dir: {getattr(storage, '__dict__', {})}")
    # Try a write
    test_key = "m2_test_photo.jpg"
    try:
        storage.put(test_key, TINY_JPEG, content_type="image/jpeg")
        print(f"storage.put OK for {test_key}")
        # Try read
        try:
            data = storage.get(test_key)
            print(f"storage.get OK, {len(data)} bytes")
        except Exception as e:
            print(f"storage.get RAISED: {type(e).__name__}: {e}")
    except Exception as e:
        print(f"storage.put RAISED: {type(e).__name__}: {e}")
        traceback.print_exc()
except Exception as e:
    print(f"Could not construct storage: {type(e).__name__}: {e}")
    traceback.print_exc()