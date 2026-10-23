"""Factory that picks the job-runner backend from settings + environment.

  * development / test : InProcessRunner (no Redis required)
  * staging / production: RQRunner, and REDIS_URL must be set
                         — otherwise the app refuses to start

This is the job-runner half of the "production refuses to start with dev
defaults" validation.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.jobs.base import JobRunner
from app.jobs.in_process import InProcessRunner
from app.jobs.rq_runner import RQRunner


def _build_runner(settings: Settings) -> JobRunner:
    if settings.environment in ("development", "test"):
        return InProcessRunner(max_workers=2)

    if not settings.redis_url:
        raise RuntimeError(
            f"Job runner RQRunner requires REDIS_URL to be set "
            f"when ENVIRONMENT={settings.environment}"
        )

    return RQRunner(redis_url=settings.redis_url)

@lru_cache(maxsize=1)
def get_job_runner() -> JobRunner:
    return _build_runner(get_settings())
