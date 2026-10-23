"""Tests for production-defaults validation.

The Settings class must refuse to instantiate when ENVIRONMENT=production and
any of S3_ENDPOINT, S3_BUCKET, REDIS_URL, CLAMAV_HOST is missing. Development
must permit them missing. This is the enforcement of the brief's rule:
"production refuses to start with the stub scanner, local storage or
in-process runner".

These tests do not touch the database or the filesystem. They construct
Settings(...) directly with explicit arguments.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _base_args(**overrides: object) -> dict[str, object]:
    args: dict[str, object] = {
        "environment": "development",
        "secret_key": "x" * 40,
        "master_encryption_key": "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        "database_url_control": "postgresql+psycopg://u:p@localhost:5432/ctl",
        "database_url_control_admin": "postgresql+psycopg://u:p@localhost:5432/ctl",
        "database_url_tenant_template": "postgresql+psycopg://u:p@localhost:5432/{tenant_db}",
        "database_url_tenant_admin_template": "postgresql+psycopg://u:p@localhost:5432/{tenant_db}",
        "redis_url": "",
        "s3_endpoint": "",
        "s3_access_key": "",
        "s3_secret_key": "",
        "s3_bucket": "",
        "clamav_host": "",
        "allow_tenant_header_fallback": False,
    }
    args.update(overrides)
    return args


def test_development_permits_all_defaults_missing() -> None:
    s = Settings(**_base_args(environment="development"))
    assert s.environment == "development"
    assert s.s3_endpoint == ""


def test_production_permits_all_defaults_set() -> None:
    s = Settings(
        **_base_args(
            environment="production",
            redis_url="redis://localhost:6379/0",
            s3_endpoint="http://minio:9000",
            s3_bucket="payroll-files",
            s3_access_key="key",
            s3_secret_key="secret",
            clamav_host="clamav",
        )
    )
    assert s.environment == "production"


def test_production_rejects_missing_s3_endpoint() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            **_base_args(
                environment="production",
                redis_url="redis://localhost:6379/0",
                s3_bucket="payroll-files",
                clamav_host="clamav",
            )
        )
    assert "S3_ENDPOINT" in str(exc_info.value)


def test_production_rejects_missing_s3_bucket() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            **_base_args(
                environment="production",
                redis_url="redis://localhost:6379/0",
                s3_endpoint="http://minio:9000",
                clamav_host="clamav",
            )
        )
    assert "S3_BUCKET" in str(exc_info.value)


def test_production_rejects_missing_redis_url() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            **_base_args(
                environment="production",
                s3_endpoint="http://minio:9000",
                s3_bucket="payroll-files",
                clamav_host="clamav",
            )
        )
    assert "REDIS_URL" in str(exc_info.value)


def test_production_rejects_missing_clamav_host() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            **_base_args(
                environment="production",
                redis_url="redis://localhost:6379/0",
                s3_endpoint="http://minio:9000",
                s3_bucket="payroll-files",
            )
        )
    assert "CLAMAV_HOST" in str(exc_info.value)


def test_staging_permits_all_defaults_missing() -> None:
    s = Settings(**_base_args(environment="staging"))
    assert s.environment == "staging"