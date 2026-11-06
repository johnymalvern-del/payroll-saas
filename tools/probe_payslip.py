"""Probe payslip-relevant endpoints for next-turn seed."""
import inspect
from app.main import app
from app.services.payroll_runner import _formula_warnings

s = app.openapi()

print("=== formula paths ===")
for p in s["paths"]:
    if "formula" in p.lower():
        print(f"  {p}: {[m.upper() for m in s['paths'][p] if m in ('get','post','patch','put')]}")

print("\n=== earning-type paths ===")
for p in s["paths"]:
    if "earning" in p.lower():
        print(f"  {p}: {[m.upper() for m in s['paths'][p] if m in ('get','post','patch','put')]}")

print("\n=== user paths ===")
for p in s["paths"]:
    if p.endswith("/users") or "/users/" in p:
        print(f"  {p}: {[m.upper() for m in s['paths'][p] if m in ('get','post','patch')]}")

print("\n=== UserCreateIn fields ===")
for n in s["components"]["schemas"]:
    if n in ("UserCreateIn", "UserPatchIn", "UserOut"):
        print(f"  {n}: {list(s['components']['schemas'][n].get('properties', {}).keys())}")

print("\n=== finalise path ===")
for p in s["paths"]:
    if "finalise" in p.lower():
        print(f"  {p}: {[m.upper() for m in s['paths'][p] if m in ('post','patch')]}")

print("\n=== _formula_warnings source ===")
print(inspect.getsource(_formula_warnings))