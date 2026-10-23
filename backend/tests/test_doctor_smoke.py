"""Smoke test for scripts/doctor.ps1.

Runs the script and asserts it exits 0. This means any regression that would
make the doctor print a false [FAIL] - which is exactly what we hit when
alembic's stderr was being wrapped as NativeCommandError - is now caught by
the test suite, not only by manual inspection.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCTOR = REPO_ROOT / "scripts" / "doctor.ps1"


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows-only")
def test_doctor_script_exits_zero() -> None:
    assert DOCTOR.exists(), f"doctor.ps1 not found at {DOCTOR}"
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", str(DOCTOR),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    assert result.returncode == 0, (
        f"doctor.ps1 exited {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}\n"
    )
    assert "[FAIL]" not in combined, f"doctor reported a failure:\n{combined}"