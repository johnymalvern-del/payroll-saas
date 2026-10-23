"""Factory that picks the storage backend from settings + environment.

  * development / test : LocalFileStorage
  * staging / production: S3Storage (must be fully configured)
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.core.config import Settings, get_settings
from app.storage.base import Storage
from app.storage.local import LocalFileStorage
from app.storage.s3 import S3Storage


def _local_base_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "var" / "storage"


def _build_storage(settings: Settings) -> Storage:
    if settings.environment in ("development", "test"):
        return LocalFileStorage(base_dir=_local_base_dir())

    missing = [
        name
        for name, value in (
            ("S3_ENDPOINT", settings.s3_endpoint),
            ("S3_ACCESS_KEY", settings.s3_access_key),
            ("S3_SECRET_KEY", settings.s3_secret_key),
            ("S3_BUCKET", settings.s3_bucket),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            f"Storage backend S3Storage requires {', '.join(missing)} to be set "
            f"when ENVIRONMENT={settings.environment}"
        )

    return S3Storage(
        endpoint_url=settings.s3_endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        bucket=settings.s3_bucket,
        region=settings.s3_region,
    )


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    return _build_storage(get_settings())
