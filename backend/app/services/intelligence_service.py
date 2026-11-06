"""Intelligence service — Phase 1A foundation.

Deterministic mode resolution and mode-change recording. No recommendation
generation, no decision execution, no business-rule interpretation of any
workflow.

Fails closed:
  - missing settings row -> Traditional
  - unknown workflow      -> AppError (422)
  - no override active    -> company default
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tenant.models.intelligence import (
    MODES,
    WORKFLOWS,
    IntelligenceModeChangeLog,
    IntelligenceSettings,
    IntelligenceWorkflowMode,
)


def _validate_mode(mode: str) -> None:
    if mode not in MODES:
        raise AppError(
            "invalid_mode",
            f"mode must be one of {MODES}",
            422,
            {"mode": mode, "allowed": list(MODES)},
        )


def _validate_workflow(workflow: str) -> None:
    if workflow not in WORKFLOWS:
        raise AppError(
            "unknown_workflow",
            f"workflow {workflow!r} is not registered",
            422,
            {"workflow": workflow, "allowed": list(WORKFLOWS)},
        )


def _get_or_create_settings(db: Session) -> IntelligenceSettings:
    settings = db.scalar(select(IntelligenceSettings).limit(1))
    if settings is None:
        settings = IntelligenceSettings(
            id=uuid.uuid4(),
            default_mode="traditional",
            row_version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(settings)
        db.flush()
    return settings


def resolve_effective_mode(db: Session, workflow: str) -> str:
    """Deterministic mode resolution.

    1. Validate workflow (unknown -> 422).
    2. Read company default (missing -> 'traditional').
    3. Read active override whose effective_from <= now (if any).
    4. Return override mode, else company default.
    """
    _validate_workflow(workflow)
    settings = db.scalar(select(IntelligenceSettings).limit(1))
    company_default = settings.default_mode if settings else "traditional"
    now = datetime.now(timezone.utc)
    override = db.scalar(
        select(IntelligenceWorkflowMode).where(
            IntelligenceWorkflowMode.workflow == workflow,
            IntelligenceWorkflowMode.is_active.is_(True),
            IntelligenceWorkflowMode.effective_from <= now,
        )
    )
    return override.mode if override else company_default


def record_mode_change(
    db: Session,
    user: Any,
    *,
    workflow: str | None,
    previous_mode: str,
    new_mode: str,
    reason: str,
    effective_from: datetime,
    audit_id: uuid.UUID | None,
) -> IntelligenceModeChangeLog:
    if workflow is not None:
        _validate_workflow(workflow)
    _validate_mode(previous_mode)
    _validate_mode(new_mode)
    if not reason or not reason.strip():
        raise AppError(
            "reason_required", "A reason is required for mode changes", 422
        )
    log = IntelligenceModeChangeLog(
        id=uuid.uuid4(),
        changed_by_user_id=getattr(user, "id", None),
        changed_at=datetime.now(timezone.utc),
        workflow=workflow,
        previous_mode=previous_mode,
        new_mode=new_mode,
        reason=reason.strip(),
        effective_from=effective_from,
        audit_id=audit_id,
    )
    db.add(log)
    db.flush()
    return log
