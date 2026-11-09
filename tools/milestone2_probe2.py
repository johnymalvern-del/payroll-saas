"""Milestone 2 — probe #2.

Read exactly what is needed to write the two fixes:
- Full _process_punch source (transaction structure)
- Full app/storage directory contents
- Whether PunchOut schema can carry a warnings field
- Reproduce storage.put in isolation
"""
import base64
import inspect
import sys
import traceback
from pathlib import Path

BE = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BE))


def dump_full(path, first=None, last=None):
    p = Path(path)
    if not p.exists():
        print(f"--- {path} NOT FOUND ---")
        return
    lines = p.read_text(encoding="utf-8").split("\n")
    total = len(lines)
    if first is None:
        first = 1
    if last is None:
        last = total
    print(f"--- {path} lines {first}–{last} of {total} ---")
    for i in range(first - 1, min(last, total)):
        print(f"{i+1:4}: {lines[i]}")
    print()


# ============================================================
print("=" * 60)
print("SECTION 1 — _process_punch FULL SOURCE (from punches.py)")
print("=" * 60)
src = (BE / "app" / "api" / "v1" / "punches.py").read_text(encoding="utf-8")
lines = src.split("\n")
# Find _process_punch start and end
start = None
for i, ln in enumerate(lines):
    if "def _process_punch" in ln:
        start = i
        break
if start is None:
    print("NOT FOUND")
else:
    # find end: next top-level def or end of file
    end = start + 1
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("def ") or lines[j].startswith("@router"):
            end = j
            break
    else:
        end = len(lines)
    print(f"--- _process_punch: lines {start+1}–{end} of {len(lines)} ---")
    for j in range(start, end):
        print(f"{j+1:4}: {lines[j]}")
    print()

# ============================================================
print("=" * 60)
print("SECTION 2 — app/storage directory tree")
print("=" * 60)
storage_dir = BE / "app" / "storage"
if storage_dir.exists():
    for p in sorted(storage_dir.rglob("*")):
        if p.is_file() and not p.name.endswith(".pyc"):
            print(f"  {p.relative_to(BE)}  ({p.stat().st_size} bytes)")
else:
    print(f"  {storage_dir} NOT FOUND")

# ============================================================
print("=" * 60)
print("SECTION 3 — app/storage/factory.py FULL")
print("=" * 60)
dump_full(BE / "app" / "storage" / "factory.py")

# ============================================================
print("=" * 60)
print("SECTION 4 — app/storage/base.py FULL (if exists)")
print("=" * 60)
base_file = BE / "app" / "storage" / "base.py"
if base_file.exists():
    dump_full(base_file)
else:
    # try __init__.py
    print("  base.py not found; dumping __init__.py")
    dump_full(BE / "app" / "storage" / "__init__.py")

# ============================================================
print("=" * 60)
print("SECTION 5 — every concrete storage impl in app/storage/")
print("=" * 60)
for p in sorted(storage_dir.glob("*.py")) if storage_dir.exists() else []:
    if p.name in ("factory.py", "base.py", "__init__.py"):
        continue
    print(f"--- {p.relative_to(BE)} ---")
    print(p.read_text(encoding="utf-8")[:3000])
    print()

# ============================================================
print("=" * 60)
print("SECTION 6 — config: storage-related settings")
print("=" * 60)
from app.core.config import get_settings
try:
    settings = get_settings()
    attrs = [a for a in dir(settings) if not a.startswith("_")
             and any(k in a.lower() for k in
                     ("storage", "upload", "s3", "media", "photo", "file"))]
    for a in attrs:
        try:
            v = getattr(settings, a)
            # mask long strings
            s = str(v)
            if len(s) > 100:
                s = s[:100] + "..."
            print(f"  {a} = {s}")
        except Exception as e:
            print(f"  {a} = <error: {e}>")
except Exception as e:
    print(f"  get_settings failed: {e}")

# ============================================================
print("=" * 60)
print("SECTION 7 — call get_storage() and inspect result")
print("=" * 60)
try:
    from app.storage.factory import get_storage
    st = get_storage()
    print(f"  storage class: {type(st).__name__}")
    print(f"  storage module: {type(st).__module__}")
    print(f"  storage attrs: {[a for a in dir(st) if not a.startswith('_')]}")
    # Try to introspect the class __init__
    print(f"  class __init__ sig: {inspect.signature(st.__class__.__init__)}")
except Exception as e:
    print(f"  get_storage() RAISED: {type(e).__name__}: {e}")
    traceback.print_exc()

# ============================================================
print("=" * 60)
print("SECTION 8 — REPRODUCE storage.put failure")
print("=" * 60)
# Valid 1x1 JPEG (magic bytes ffd8ff)
TINY_JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00d2cf20ffd9")

try:
    from app.storage.factory import get_storage
    st = get_storage()
    print(f"  storage: {type(st).__name__}")
    try:
        key = st.put(TINY_JPEG, content_type="image/jpeg", suffix=".jpg") if "suffix" in inspect.signature(st.put).parameters else st.put(TINY_JPEG)
        print(f"  put() returned: {key!r}")
    except TypeError:
        # try common signatures
        for attempt in (
            lambda: st.put(TINY_JPEG, "image/jpeg"),
            lambda: st.put(TINY_JPEG, content_type="image/jpeg"),
            lambda: st.put(b"test", TINY_JPEG),
        ):
            try:
                r = attempt()
                print(f"  put() returned: {r!r}")
                break
            except Exception as e2:
                print(f"  put attempt failed: {type(e2).__name__}: {e2}")
    except Exception as e:
        print(f"  put() RAISED: {type(e).__name__}: {e}")
        traceback.print_exc()
except Exception as e:
    print(f"  Could not get storage: {type(e).__name__}: {e}")

# ============================================================
print("=" * 60)
print("SECTION 9 — PunchOut schema")
print("=" * 60)
dump_full(BE / "app" / "api" / "v1" / "punches_schemas.py", first=47, last=110)

# ============================================================
print("=" * 60)
print("SECTION 10 — _process_punch's return annotation and caller signature")
print("=" * 60)
# Caller usage: line 267 in Section 1: punch, _ = _process_punch(...)
# What's the second element used for?
print("  Callers of _process_punch:")
for m in ("submit_punch", "submit_punch_batch"):
    for i, ln in enumerate(lines):
        if f"def {m}" in ln:
            # scan 10 lines
            for j in range(i, min(i + 15, len(lines))):
                if "_process_punch" in lines[j]:
                    print(f"    {m} line {j+1}: {lines[j].strip()}")