"""Final Milestone 2 probe: LocalFileStorage API + Storage base class."""
import inspect
import sys
from pathlib import Path

BE = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BE))

print("=" * 60)
print("SECTION 1 — storage folder files")
print("=" * 60)
sd = BE / "app" / "storage"
for p in sorted(sd.rglob("*.py")):
    print(f"  {p.relative_to(BE)}  ({p.stat().st_size} bytes)")

print("\n" + "=" * 60)
print("SECTION 2 — LocalFileStorage FULL SOURCE")
print("=" * 60)
from app.storage.factory import get_storage
st = get_storage()
cls = type(st)
print(f"class: {cls.__name__} @ {cls.__module__}")
try:
    print(inspect.getsource(cls))
except Exception as e:
    print(f"  could not getsource: {e}")

print("\n" + "=" * 60)
print("SECTION 3 — all public methods/properties on LocalFileStorage")
print("=" * 60)
for name in sorted(dir(st)):
    if name.startswith("_"):
        continue
    try:
        attr = getattr(st, name)
        kind = "method" if callable(attr) else "attr"
        if callable(attr):
            try:
                sig = inspect.signature(attr)
                print(f"  {kind} {name}{sig}")
            except (ValueError, TypeError):
                print(f"  {kind} {name}(<no sig>)")
        else:
            print(f"  {kind} {name} = {attr!r}")
    except Exception as e:
        print(f"  {name} <error: {e}>")

print("\n" + "=" * 60)
print("SECTION 4 — Storage base class source")
print("=" * 60)
# Find Storage class from app.storage.base or wherever
for modname in ("app.storage.base", "app.storage"):
    try:
        mod = __import__(modname, fromlist=["Storage"])
        Storage = getattr(mod, "Storage", None)
        if Storage is not None:
            print(f"Storage class found in {modname}")
            try:
                print(inspect.getsource(Storage))
            except Exception as e:
                print(f"  cannot getsource: {e}")
            break
    except ImportError:
        pass
else:
    print("Storage base class not found via base/__init__")

print("\n" + "=" * 60)
print("SECTION 5 — every 'storage.' call site in app/")
print("=" * 60)
for p in sorted((BE / "app").rglob("*.py")):
    try:
        src = p.read_text(encoding="utf-8")
    except Exception:
        continue
    for i, ln in enumerate(src.split("\n"), 1):
        if "storage." in ln and "storage." in ln.replace(
            "# storage.", ""
        ).replace('"', "").replace("'", "") and not ln.strip().startswith("#"):
            print(f"  {p.relative_to(BE)}:{i}: {ln.strip()}")