
"""Rate-limiter tests."""
from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.rate_limiter.in_memory import InMemoryRateLimiter


def test_in_memory_allow_then_deny() -> None:
    rl = InMemoryRateLimiter()
    for _ in range(5):
        assert rl.hit("ip:1.2.3.4", limit=5, window_seconds=60)
    assert not rl.hit("ip:1.2.3.4", limit=5, window_seconds=60)
    assert rl.hit("ip:5.6.7.8", limit=5, window_seconds=60)


def test_in_memory_window_expiry() -> None:
    rl = InMemoryRateLimiter()
    for _ in range(3):
        assert rl.hit("k", limit=3, window_seconds=1)
    assert not rl.hit("k", limit=3, window_seconds=1)
    time.sleep(1.05)
    assert rl.hit("k", limit=3, window_seconds=1)


def test_production_multiworker_requires_redis() -> None:
    base = dict(
        environment="production",
        secret_key="x" * 40,
        master_encryption_key="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        database_url_control="postgresql+psycopg://u:p@localhost:5432/ctl",
        database_url_control_admin="postgresql+psycopg://u:p@localhost:5432/ctl",
        database_url_tenant_template="postgresql+psycopg://u:p@localhost:5432/{tenant_db}",
        database_url_tenant_admin_template="postgresql+psycopg://u:p@localhost:5432/{tenant_db}",
        database_url_superuser="postgresql+psycopg://u:p@localhost:5432/postgres",
        redis_url="",
        s3_endpoint="http://minio:9000",
        s3_bucket="payroll-files",
        s3_access_key="key",
        s3_secret_key="secret",
        clamav_host="clamav",
        workers_count=4,
        allow_tenant_header_fallback=False,
    )
    with pytest.raises(ValidationError, match="REDIS_URL"):
        Settings(_env_file=None, **base)  # type: ignore[call-arg]
