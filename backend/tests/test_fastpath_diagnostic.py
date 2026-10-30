"""Diagnostic: is the test fast path active?

Skips when env var is not set (BEFORE run). Asserts swap state when env
var is set (AFTER run). Failure message names the exact breakage.
"""
from __future__ import annotations

import os

import pytest


def test_fastpath_state():
    if os.environ.get("PAYROLL_TEST_TEMPLATE_DB") != "1":
        pytest.skip("PAYROLL_TEST_TEMPLATE_DB not set")
    from app.services import provisioning
    assert provisioning._TEST_TEMPLATE_ENABLED, (
        "_TEST_TEMPLATE_ENABLED is False: the swap never fired. "
        "Did the conftest fixture run before disposable_tenant?"
    )
    fn = provisioning._run_tenant_migrations
    assert getattr(fn, "__name__", "") == "_4a_run_migrations_from_template", (
        f"_run_tenant_migrations is {getattr(fn, '__name__', fn)!r}, "
        f"expected _4a_run_migrations_from_template"
    )
    assert provisioning._TEMPLATE_NAME_CACHE is not None, (
        "template name never cached: bootstrap fixture did not run"
    )
    assert provisioning._TEMPLATE_VERSION_CACHE is not None, (
        "template version never cached: bootstrap fixture did not finish"
    )

# END OF FILE
