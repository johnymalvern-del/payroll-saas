"""Endpoint-level permission wiring for payroll routes (Chapter 4).

For every payroll route introduced in Bundles 003b and 003c, assert:
  1. The route is registered on the FastAPI app at the expected (method, path).
  2. The route depends on require_permission(<expected Permission>).

The extractor walks the route's dependant tree and looks for a Permission enum
in any dependency closure. It is robust to FastAPI's wrapping.
"""
from __future__ import annotations

import pytest

from app.core.permissions import Permission


# ---------------------------------------------------------------------------
# Expected routes: (method, path, expected_permission)
# ---------------------------------------------------------------------------

EXPECTED_ROUTES: list[tuple[str, str, Permission]] = [
    # Bundle 003b — settings
    ("GET",   "/api/v1/payroll/settings", Permission.PAYROLL_PREVIEW),
    ("PATCH", "/api/v1/payroll/settings", Permission.PAYROLL_FINALISE),
    # Bundle 003b — earning types
    ("GET",   "/api/v1/payroll/earning-types", Permission.PAYROLL_PREVIEW),
    ("GET",   "/api/v1/payroll/earning-types/{type_id}", Permission.PAYROLL_PREVIEW),
    ("POST",  "/api/v1/payroll/earning-types", Permission.PAYROLL_FINALISE),
    ("PATCH", "/api/v1/payroll/earning-types/{type_id}", Permission.PAYROLL_FINALISE),
    ("POST",  "/api/v1/payroll/earning-types/{type_id}/deactivate", Permission.PAYROLL_FINALISE),
    # Bundle 003b — deduction types
    ("GET",   "/api/v1/payroll/deduction-types", Permission.PAYROLL_PREVIEW),
    ("GET",   "/api/v1/payroll/deduction-types/{type_id}", Permission.PAYROLL_PREVIEW),
    ("POST",  "/api/v1/payroll/deduction-types", Permission.PAYROLL_FINALISE),
    ("PATCH", "/api/v1/payroll/deduction-types/{type_id}", Permission.PAYROLL_FINALISE),
    ("POST",  "/api/v1/payroll/deduction-types/{type_id}/deactivate", Permission.PAYROLL_FINALISE),
    # Bundle 003c — employee earnings
    ("GET",   "/api/v1/payroll/employees/{employee_id}/earnings", Permission.PAYROLL_PREVIEW),
    ("GET",   "/api/v1/payroll/employees/{employee_id}/earnings/{item_id}", Permission.PAYROLL_PREVIEW),
    ("POST",  "/api/v1/payroll/employees/{employee_id}/earnings", Permission.PAY_RATE_REQUEST),
    ("PATCH", "/api/v1/payroll/employees/{employee_id}/earnings/{item_id}", Permission.PAY_RATE_REQUEST),
    ("POST",  "/api/v1/payroll/employees/{employee_id}/earnings/{item_id}/deactivate", Permission.PAY_RATE_REQUEST),
    # Bundle 003c — employee deductions
    ("GET",   "/api/v1/payroll/employees/{employee_id}/deductions", Permission.PAYROLL_PREVIEW),
    ("GET",   "/api/v1/payroll/employees/{employee_id}/deductions/{item_id}", Permission.PAYROLL_PREVIEW),
    ("POST",  "/api/v1/payroll/employees/{employee_id}/deductions", Permission.PAY_RATE_REQUEST),
    ("PATCH", "/api/v1/payroll/employees/{employee_id}/deductions/{item_id}", Permission.PAY_RATE_REQUEST),
    ("POST",  "/api/v1/payroll/employees/{employee_id}/deductions/{item_id}/deactivate", Permission.PAY_RATE_REQUEST),
]


# ---------------------------------------------------------------------------
# Route discovery + permission extraction
# ---------------------------------------------------------------------------

def _route_map():
    from fastapi.routing import APIRoute
    from app.main import app
    out: dict[tuple[str, str], APIRoute] = {}
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        for m in r.methods:
            if m in ("HEAD", "OPTIONS"):
                continue
            out[(m, r.path)] = r
    return out


def _extract_permissions(route) -> set[Permission]:
    found: set[Permission] = set()
    stack = [route.dependant]
    while stack:
        d = stack.pop()
        fn = getattr(d, "call", None)
        if fn is not None and getattr(fn, "__closure__", None):
            for cell in fn.__closure__:
                try:
                    v = cell.cell_contents
                except ValueError:
                    continue
                if isinstance(v, Permission):
                    found.add(v)
        stack.extend(getattr(d, "dependencies", []) or [])
    return found


# ---------------------------------------------------------------------------
# Parametrized tests
# ---------------------------------------------------------------------------

_IDS = [f"{m}-{p}-{perm.value}" for m, p, perm in EXPECTED_ROUTES]


@pytest.mark.parametrize("method,path,expected_perm", EXPECTED_ROUTES, ids=_IDS)
def test_route_registered(method: str, path: str, expected_perm: Permission) -> None:
    routes = _route_map()
    key = (method, path)
    assert key in routes, (
        f"Route {method} {path} not registered. "
        f"Available payroll routes: "
        f"{sorted(k for k in routes if 'payroll' in k[1])}"
    )


@pytest.mark.parametrize("method,path,expected_perm", EXPECTED_ROUTES, ids=_IDS)
def test_route_has_expected_permission(method: str, path: str, expected_perm: Permission) -> None:
    routes = _route_map()
    route = routes.get((method, path))
    assert route is not None, f"Route {method} {path} not found"
    perms = _extract_permissions(route)
    assert expected_perm in perms, (
        f"{method} {path}: expected permission {expected_perm.value!r}, "
        f"found {sorted(p.value for p in perms)}"
    )


def test_payroll_routes_all_have_a_permission() -> None:
    """Every route under /api/v1/payroll/ must declare at least one Permission."""
    routes = _route_map()
    offenders = []
    for (method, path), route in routes.items():
        if not path.startswith("/api/v1/payroll"):
            continue
        if not _extract_permissions(route):
            offenders.append(f"{method} {path}")
    assert not offenders, f"payroll routes missing require_permission: {offenders}"

# END OF FILE
