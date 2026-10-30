"""4A-bis guard tests: fast paths only in test env; production unchanged."""
from __future__ import annotations
import os
import subprocess
import sys


def _isolated(code, drop_env=()):
    env = {k: v for k, v in os.environ.items() if k not in drop_env}
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=30)


def test_argon2_default_strong_without_env():
    r = _isolated(
        "from app.core.security import _4a_current_hasher; h=_4a_current_hasher(); print(h.memory_cost, h.time_cost, h.parallelism)",
        drop_env={"PAYROLL_TEST_FAST_HASH"},
    )
    assert r.returncode == 0, r.stderr
    mc, tc, par = r.stdout.strip().split()
    assert int(mc) >= 32768
    assert int(tc) >= 2
    assert int(par) >= 1


def test_argon2_weak_with_env_isolated():
    env = dict(os.environ)
    env["PAYROLL_TEST_FAST_HASH"] = "1"
    r = subprocess.run(
        [sys.executable, "-c", "from app.core.security import _4a_current_hasher; h=_4a_current_hasher(); print(h.memory_cost, h.time_cost)"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    mc, tc = r.stdout.strip().split()
    assert int(mc) < 32768
    assert int(tc) < 3


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
