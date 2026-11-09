"""Probe #4 — final. Just the two test helpers we haven't seen."""
import re
from pathlib import Path

BE = Path(__file__).resolve().parent.parent / "backend"
p = BE / "tests" / "test_punches.py"
src = p.read_text(encoding="utf-8")
lines = src.split("\n")

for name in ("_post", "_payload"):
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith(f"def {name}"):
            start = i
            break
    if start is None:
        print(f"--- {name} NOT FOUND ---")
        continue
    end = start + 1
    while end < len(lines) and not (
        lines[end].startswith("def ")
        or lines[end].startswith("class ")
        or lines[end].startswith("@pytest")
        or lines[end].startswith("# ====")
    ):
        end += 1
    print(f"--- {name}: lines {start+1}–{end} ---")
    for j in range(start, end):
        print(f"{j+1:4}: {lines[j]}")
    print()

# Also look for existing test that already sends a photo (section 1 of probes
# showed happy path deliberately not tested; confirm)
print("--- Any test mentioning photo_base64 ---")
for i, ln in enumerate(lines, 1):
    if "photo_base64" in ln:
        print(f"{i:4}: {ln}")

# And any _TINY / _b64 constant already defined
print("\n--- Photo constants already defined in file ---")
for i, ln in enumerate(lines, 1):
    if re.search(r"_TINY|_JPEG|_PNG|b64encode|bytes\.fromhex\('ffd8", ln):
        print(f"{i:4}: {ln}")