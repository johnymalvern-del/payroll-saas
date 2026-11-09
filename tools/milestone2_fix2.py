"""Milestone 2 fix #2: scanner call site matches base class contract.

Two adjacent bugs found by the Defect A regression test in the same
4-line photo-processing block:
  1. scanner.scan(photo_bytes, filename='...') raises TypeError: base
     contract is scan(self, data) -> ScanResult.
  2. `if not scan_ok:` treats the returned ScanResult as a truthy boolean;
     the correct check is `scan_result.clean`.
"""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "backend" / "app" / "api" / "v1" / "punches.py"
s = P.read_text(encoding="utf-8")

old = (
    "        scan_ok = scanner.scan(photo_bytes, filename='punch_photo.jpg')\n"
    "        if not scan_ok:\n"
    "            raise AppError('photo_scan_failed', 'Photo failed virus scan', 400)\n"
)
new = (
    "        scan_result = scanner.scan(photo_bytes)\n"
    "        if not scan_result.clean:\n"
    "            raise AppError('photo_scan_failed', 'Photo failed virus scan', 400)\n"
)
if old not in s:
    raise SystemExit("FATAL: photo-scan block not found")
s = s.replace(old, new, 1)
P.write_text(s, encoding="utf-8")
print("patched: scanner.scan(photo_bytes) + scan_result.clean check")