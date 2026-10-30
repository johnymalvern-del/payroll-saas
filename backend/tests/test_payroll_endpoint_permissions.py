"""Endpoint-level permission wiring for payroll routes (Chapter 4)."""
from __future__ import annotations

import pytest

from app.core.permissions import Permission


EXPECTED_ROUTES: list[tuple[str, str, Permission]] = [
    # 003b — settings
    ("GET",   "/api/v1/payroll/settings", Permission.PAYROLL_PREVIEW),
    ("PATCH", "/api/v1/payroll/settings", Permission.PAYROLL_FINALISE),
    # 003b — earning types
    ("GET",   "/api/v1/payroll/earning-types", Permission.PAYROLL_PREVIEW),
    ("GET",   "/api/v1/payroll/earning-types/{type_id}", Permission.PAYROLL_PREVIEW),
    ("POST",  "/api/v1/payroll/earning-types", Permission.PAYROLL_FINALISE),
    ("PATCH", "/api/v1/payroll/earning-types/{type_id}", Permission.PAYROLL_FINALISE),
    ("POST",  "/api/v1/payroll/earning-types/{type_id}/deactivate", Permission.PAYROLL_FINALISE),
    # 003b — deduction types
    ("GET",   "/api/v1/payroll/deduction-types", Permission.PAYROLL_PREVIEW),
    ("GET",   "/api/v1/payroll/deduction-types/{type_id}", Permission.PAYROLL_PREVIEW),
    ("POST",  "/api/v1/payroll/deduction-types", Permission.PAYROLL_FINALISE),
    ("PATCH", "/api/v1/payroll/deduction-types/{type_id}", Permission.PAYROLL_FINALISE),
    ("POST",  "/api/v1/payroll/deduction-types/{type_id}/deactivate", Permission.PAYROLL_FINALISE),
    # 003c — employee earnings (read)
    ("GET",   "/api/v1/payroll/employees/{employee_id}/earnings", Permission.PAYROLL_PREVIEW),
    ("GET",   "/api/v1/payroll/employees/{employee_id}/earnings/{item_id}", Permission.PAYROLL_PREVIEW),
    # 004a-iv-b — employee earnings (write submits change request)
    ("POST",  "/api/v1/payroll/employees/{employee_id}/earnings", Permission.PAY_RATE_REQUEST),
    ("PATCH", "/api/v1/payroll/employees/{employee_id}/earnings/{item_id}", Permission.PAY_RATE_REQUEST),
    ("POST",  "/api/v1/payroll/employees/{employee_id}/earnings/{item_id}/deactivate", Permission.PAY_RATE_REQUEST),
    # 003c — employee deductions (read)
    ("GET",   "/api/v1/payroll/employees/{employee_id}/deductions", Permission.PAYROLL_PREVIEW),
    ("GET",   "/api/v1/payroll/employees/{employee_id}/deductions/{item_id}", Permission.PAYROLL_PREVIEW),
    # 004a-iv-b — employee deductions (write submits change request)
    ("POST",  "/api/v1/payroll/employees/{employee_id}/deductions", Permission.PAY_RATE_REQUEST),
    ("PATCH", "/api/v1/payroll/employees/{employee_id}/deductions/{item_id}", Permission.PAY_RATE_REQUEST),
    ("POST",  "/api/v1/payroll/employees/{employee_id}/deductions/{item_id}/deactivate", Permission.PAY_RATE_REQUEST),
    # 004a-iv-b — employee fields
    ("GET",   "/api/v1/payroll/employees/{employee_id}/fields", Permission.PAYROLL_PREVIEW),
    ("POST",  "/api/v1/payroll/employees/{employee_id}/fields", Permission.PAY_RATE_REQUEST),
    # 004a-iv-c — system types seed
    ("POST",  "/api/v1/payroll/earning-types/ensure-system", Permission.PAYROLL_FINALISE),
    # 004a-i — formula readiness
    ("GET",   "/api/v1/payroll-formulas/readiness", Permission.PAYROLL_PREVIEW),
    ("POST",  "/api/v1/payroll-formulas/{code}/acknowledge", Permission.PAYROLL_FINALISE),
    # 004a-iv-a — change requests
    ("POST",  "/api/v1/payroll/change-requests", Permission.PAY_RATE_REQUEST),
    ("GET",   "/api/v1/payroll/change-requests", Permission.PAY_RATE_VIEW),
    ("GET",   "/api/v1/payroll/change-requests/{request_id}", Permission.PAY_RATE_VIEW),
    ("POST",  "/api/v1/payroll/change-requests/{request_id}/approve", Permission.PAY_RATE_APPROVE),
    ("POST",  "/api/v1/payroll/change-requests/{request_id}/reject", Permission.PAY_RATE_APPROVE),
    ("POST",  "/api/v1/payroll/change-requests/{request_id}/cancel", Permission.PAY_RATE_REQUEST),
]


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


_IDS = [f"{m}-{p}-{perm.value}" for m, p, perm in EXPECTED_ROUTES]


@pytest.mark.parametrize("method,path,expected_perm", EXPECTED_ROUTES, ids=_IDS)
def test_route_registered(method: str, path: str, expected_perm: Permission) -> None:
    routes = _route_map()
    key = (method, path)
    assert key in routes, (
        f"Route {method} {path} not registered. "
        f"Available payroll routes: {sorted(k for k in routes if 'payroll' in k[1])}"
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
    routes = _route_map()
    offenders = []
    for (method, path), route in routes.items():
        if not path.startswith("/api/v1/payroll"):
            continue
        if not _extract_permissions(route):
            offenders.append(f"{method} {path}")
    assert not offenders, f"payroll routes missing require_permission: {offenders}"

# END OF FILE
