
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "staging", "production"] = "development"

    secret_key: str = Field(..., min_length=32)
    master_encryption_key: str

    database_url_control: str
    database_url_control_admin: str
    database_url_tenant_template: str
    database_url_tenant_admin_template: str
    database_url_superuser: str

    redis_url: str

    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str
    s3_region: str = "us-east-1"

    clamav_host: str = "clamav"
    clamav_port: int = 3310

    cors_origins: str = ""

    log_level: str = "INFO"

    allow_tenant_header_fallback: bool = False

    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    login_rate_limit_per_minute: int = 20
    refresh_reuse_leeway_seconds: int = 10
    refresh_token_retention_days: int = 30

    workers_count: int = 1

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def tenant_header_fallback_active(self) -> bool:
        return self.allow_tenant_header_fallback and self.environment in ("development", "test")

    @model_validator(mode="after")
    def _validate_invariants(self) -> "Settings":
        if self.environment == "production" and self.allow_tenant_header_fallback:
            raise ValueError(
                "ALLOW_TENANT_HEADER_FALLBACK cannot be enabled in production"
            )
        try:
            Fernet(self.master_encryption_key.encode("ascii"))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                f"MASTER_ENCRYPTION_KEY must be a valid Fernet key: {exc}"
            ) from exc
        return self

    @model_validator(mode="after")
    def _validate_production_defaults(self) -> "Settings":
        if self.environment != "production":
            return self
        missing: list[str] = []
        if not self.s3_endpoint:
            missing.append("S3_ENDPOINT")
        if not self.s3_bucket:
            missing.append("S3_BUCKET")
        if not self.redis_url:
            missing.append("REDIS_URL")
        if not self.clamav_host:
            missing.append("CLAMAV_HOST")
        if missing:
            raise ValueError(
                "Production requires "
                + ", ".join(missing)
                + " (development defaults are not permitted in production)"
            )
        return self

    @model_validator(mode="after")
    def _validate_worker_safety(self) -> "Settings":
        if self.environment == "production" and self.workers_count > 1:
            if not self.redis_url:
                raise ValueError(
                    "Production with workers_count > 1 requires REDIS_URL "
                    "(in-memory rate limiter cannot be shared across workers)"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
