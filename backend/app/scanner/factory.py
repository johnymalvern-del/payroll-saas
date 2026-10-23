"""Factory that picks the scanner backend from settings + environment.

  * development / test : NoOpScanner
  * staging / production: ClamAVScanner, and CLAMAV_HOST must be set
                         - otherwise the app refuses to start

This is the scanner half of the "production refuses dev defaults" validation.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.scanner.base import VirusScanner
from app.scanner.clamav import ClamAVScanner
from app.scanner.noop import NoOpScanner


def _build_scanner(settings: Settings) -> VirusScanner:
    if settings.environment in ("development", "test"):
        return NoOpScanner()

    if not settings.clamav_host:
        raise RuntimeError(
            f"Scanner backend ClamAVScanner requires CLAMAV_HOST to be set "
            f"when ENVIRONMENT={settings.environment}"
        )

    return ClamAVScanner(host=settings.clamav_host, port=settings.clamav_port)


@lru_cache(maxsize=1)
def get_scanner() -> VirusScanner:
    return _build_scanner(get_settings())