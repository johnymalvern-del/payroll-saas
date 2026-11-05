"""Probe run_preview internals: does any _build_* helper accept a through/
end date, so as_of can be threaded without rewriting the pipeline?"""
import inspect
from app.services import payroll_runner as pr

print("=== run_preview source ===")
print(inspect.getsource(pr.run_preview))

print("\n=== signatures of _build_* and helpers ===")
for name in dir(pr):
    if name.startswith("_") and (
        "build" in name or "rate" in name or "monthly" in name or "daily" in name
    ):
        obj = getattr(pr, name)
        if callable(obj):
            try:
                sig = inspect.signature(obj)
                print(f"{name}{sig}")
            except Exception:
                pass

print("\n=== run_preview body: does it slice attendance by date? ===")
src = inspect.getsource(pr.run_preview)
for i, line in enumerate(src.split("\n"), 1):
    if any(k in line.lower() for k in ("attendance", "work_date", "end_date", "cutoff", "as_of")):
        print(f"  L{i}: {line.strip()[:140]}")

print("\n=== _build_attendance_earnings body: date filter? ===")
fn = getattr(pr, "_build_attendance_earnings", None)
if fn:
    fsrc = inspect.getsource(fn)
    for i, line in enumerate(fsrc.split("\n"), 1):
        if any(k in line.lower() for k in ("attendance", "work_date", "end_date", "cutoff", "as_of")):
            print(f"  L{i}: {line.strip()[:140]}")