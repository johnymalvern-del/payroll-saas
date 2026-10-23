"""NoOpScanner - development default.

Logs a warning that scanning is disabled, then returns clean. This exists so
development does not require a running ClamAV service. The Settings validator
in app/core/config.py refuses to boot the app in production if this class is
the configured scanner.
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.scanner.base import ScanResult, VirusScanner

log = get_logger("app.scanner.noop")


class NoOpScanner(VirusScanner):
    def scan(self, data: bytes) -> ScanResult:
        log.warning(
            "scanner.noop_invoked",
            reason="scanning_disabled",
            bytes=len(data),
        )
        return ScanResult(clean=True, engine="noop", detail="scanning disabled")