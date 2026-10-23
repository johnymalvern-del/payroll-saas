
"""Refresh-token cleanup job.

Deletes refresh_token rows that expired more than `refresh_token_retention_days`
ago, and then deletes refresh_token_family rows that have no remaining tokens
and whose newest token is older than the same cutoff.

The job must be enqueued with the current tenant's database name so it runs
against the correct tenant DB:

    get_job_runner().enqueue(
        cleanup_expired_refresh_tokens,
        tenant_db_name="tenant_demo",
        retention_days=30,
    )
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.engine import create_engine

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.tenant.session import get_tenant_engine
from app.models_auth_orm import RefreshToken, RefreshTokenFamily
from sqlalchemy.orm import Session

log = get_logger("app.jobs.refresh_cleanup")


def cleanup_expired_refresh_tokens(
    tenant_db_name: str,
    retention_days: int | None = None,
) -> dict[str, int]:
    settings = get_settings()
    days = retention_days if retention_days is not None else settings.refresh_token_retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    engine = get_tenant_engine(tenant_db_name)
    with Session(engine) as session:
        # 1. Delete tokens whose expires_at is before the cutoff.
        result_tokens = session.execute(
            delete(RefreshToken).where(RefreshToken.expires_at < cutoff)
        )
        tokens_deleted = result_tokens.rowcount or 0

        # 2. Delete families with no remaining tokens whose newest token is
        #    older than the cutoff. A family is "empty" if there is no token
        #    row referencing it.
        subq = (
            select(RefreshToken.family_id)
            .where(RefreshToken.family_id.is_not(None))
            .distinct()
        )
        empty_family_ids = (
            session.scalars(
                select(RefreshTokenFamily.id).where(
                    RefreshTokenFamily.id.not_in(subq),
                    RefreshTokenFamily.created_at < cutoff,
                )
            )
            .all()
        )
        families_deleted = 0
        if empty_family_ids:
            result_families = session.execute(
                delete(RefreshTokenFamily).where(
                    RefreshTokenFamily.id.in_(empty_family_ids)
                )
            )
            families_deleted = result_families.rowcount or 0

        session.commit()

    log.info(
        "refresh_cleanup.done",
        tenant=tenant_db_name,
        retention_days=days,
        tokens_deleted=tokens_deleted,
        families_deleted=families_deleted,
    )
    return {"tokens_deleted": tokens_deleted, "families_deleted": families_deleted}
