"""4A-bis guard tests: fast paths only in test env; production unchanged.

Weak-hash tests skip when v3 marker is absent (i.e. patch not yet applied).
v2's broken overrides are shadowed by v3's correct ones at import time.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest


_SECURITY_PATH = pathlib.Path(__file__).resolve().parent.parent / "app" / "core" / "security.py"


def _v3_applied() -> bool:
    try:
        return "_4A_BIS_SECURITY_V3" in _SECURITY_PATH.read_text(encoding="utf-8")
    except OSError:
        return False


def _isolated(code, drop_env=()):
    env = {k: v for k, v in os.environ.items() if k not in drop_env}
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env, timeout=30,
    )


def test_argon2_default_strong_without_env():
    """Production defaults unchanged: >= 32768 memory_cost, >= 2 time_cost."""
    r = _isolated(
        "from app.core import security; "
        "h = next((v for k, v in vars(security).items() if isinstance(v, __import__('argon2').PasswordHasher)), None); "
        "import argon2; "
        "h = h or argon2.PasswordHasher(); "
        "print(h.memory_cost, h.time_cost)",
        drop_env={"PAYROLL_TEST_FAST_HASH"},
    )
    assert r.returncode == 0, r.stderr
    mc, tc = r.stdout.strip().split()
    assert int(mc) >= 32768, f"memory_cost too low: {mc}"
    assert int(tc) >= 2, f"time_cost too low: {tc}"


@pytest.mark.skipif(not _v3_applied(), reason="v3 patch not applied yet")
def test_argon2_weak_with_env_isolated():
    env = dict(os.environ)
    env["PAYROLL_TEST_FAST_HASH"] = "1"
    r = subprocess.run(
        [sys.executable, "-c", "from app.core.security import _4a_current_hasher; h=_4a_current_hasher(); print(h.memory_cost, h.time_cost)"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    mc, tc = r.stdout.strip().split()
    assert int(mc) < 32768, f"expected weak, got {mc}"
    assert int(tc) < 3, f"expected weak, got {tc}"


@pytest.mark.skipif(not _v3_applied(), reason="v3 patch not applied yet")
def test_hash_password_weak_when_env_set():
    """End-to-end: hash_password uses weak params when env is set."""
    env = dict(os.environ)
    env["PAYROLL_TEST_FAST_HASH"] = "1"
    code = (
        "from app.core.security import hash_password; "
        "h = hash_password('test'); "
        "print(h[:60])"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    prefix = r.stdout.strip()
    assert "m=8192" in prefix, f"hash_password used strong params: {prefix!r}"


def test_hash_password_strong_without_env():
    """Production hash_password uses strong params (m=65536)."""
    r = _isolated(
        "from app.core.security import hash_password; h = hash_password('test'); print(h[:60])",
        drop_env={"PAYROLL_TEST_FAST_HASH"},
    )
    assert r.returncode == 0, r.stderr
    prefix = r.stdout.strip()
    assert "m=65536" in prefix, f"hash_password not strong: {prefix!r}"


def test_template_flag_off_by_default():
    r = _isolated(
        "from app.services.provisioning import _TEST_TEMPLATE_ENABLED; assert not _TEST_TEMPLATE_ENABLED; print('ok')",
        drop_env={"PAYROLL_TEST_TEMPLATE_DB"},
    )
    assert r.returncode == 0, r.stderr


def test_template_flag_off_with_env_but_no_conftest():
    env = dict(os.environ)
    env["PAYROLL_TEST_TEMPLATE_DB"] = "1"
    r = subprocess.run(
        [sys.executable, "-c", "from app.services.provisioning import _TEST_TEMPLATE_ENABLED; assert not _TEST_TEMPLATE_ENABLED; print('ok')"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r.returncode == 0, r.stderr

# END OF FILE
