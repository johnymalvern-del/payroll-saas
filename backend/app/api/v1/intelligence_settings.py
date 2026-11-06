"""Intelligence settings API (Phase 1A).

Company-wide default mode, per-workflow overrides, change history.
No recommendation generation. No execution. No autonomous action.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.intelligence_settings_schemas import (
    IntelligenceSettingsOut,
    ModeChangeLogListOut,
    ModeChangeLogOut,
    UpdateDefaultModeIn,
    UpdateWorkflowModeIn,
    WorkflowModeListOut,
    WorkflowModeOut,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.db.tenant.models.intelligence import (
    WORKFLOWS,
    IntelligenceModeChangeLog,
    IntelligenceSettings,
    IntelligenceWorkflowMode,
)
from app.services.intelligence_service import (
    _get_or_create_settings,
    _validate_mode,
    _validate_workflow,
    record_mode_change,
    resolve_effective_mode,
)
from app.services.payroll_audit import write_audit

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


def _to_settings_out(s: IntelligenceSettings) -> IntelligenceSettingsOut:
    return IntelligenceSettingsOut(
        id=s.id,
        default_mode=s.default_mode,
        acknowledged_at=s.acknowledged_at,
        acknowledged_by_user_id=s.acknowledged_by_user_id,
        row_version=s.row_version,
    )


def _to_workflow_out(
    workflow: str,
    settings: IntelligenceSettings,
    override: IntelligenceWorkflowMode | None,
    effective: str,
) -> WorkflowModeOut:
    return WorkflowModeOut(
        workflow=workflow,
        company_default=settings.default_mode,
        override_mode=override.mode if (override and override.is_active) else None,
        override_active=bool(override and override.is_active),
        effective_mode=effective,
        row_version=override.row_version if override else None,
        effective_from=override.effective_from if override else None,
        autonomous_capability_implemented=False,
    )


@router.get("/settings", response_model=IntelligenceSettingsOut)
def get_settings(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.INTELLIGENCE_VIEW))],
) -> IntelligenceSettingsOut:
    settings = _get_or_create_settings(db)
    db.commit()
    return _to_settings_out(settings)


@router.patch("/settings/default-mode", response_model=IntelligenceSettingsOut)
def update_default_mode(
    body: UpdateDefaultModeIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.INTELLIGENCE_MANAGE))],
) -> IntelligenceSettingsOut:
    _validate_mode(body.default_mode)
    if body.default_mode == "autonomous" and not body.acknowledged_autonomous:
        raise AppError(
            "autonomous_requires_acknowledgement",
            "Selecting Autonomous requires explicit acknowledgement",
            422,
        )
    if not body.reason or not body.reason.strip():
        raise AppError("reason_required", "A reason is required", 422)

    settings = _get_or_create_settings(db)
    if settings.row_version != body.row_version:
        raise AppError(
            "record_changed",
            f"Settings changed (current row_version {settings.row_version})",
            409,
            {"current_row_version": settings.row_version},
        )
    previous_mode = settings.default_mode
    if previous_mode == body.default_mode:
        db.commit()
        return _to_settings_out(settings)

    settings.default_mode = body.default_mode
    settings.row_version += 1
    settings.updated_at = datetime.now(timezone.utc)
    if body.default_mode == "autonomous":
        settings.acknowledged_at = datetime.now(timezone.utc)
        settings.acknowledged_by_user_id = getattr(user, "id", None)

    audit = write_audit(
        db, user,
        entity_type="intelligence_settings",
        entity_id=settings.id,
        action="intelligence.default_mode.update",
        old_value={"default_mode": previous_mode},
        new_value={"default_mode": body.default_mode},
        reason=body.reason,
    )
    db.flush()
    record_mode_change(
        db, user,
        workflow=None,
        previous_mode=previous_mode,
        new_mode=body.default_mode,
        reason=body.reason,
        effective_from=body.effective_from or datetime.now(timezone.utc),
        audit_id=getattr(audit, "id", None),
    )
    db.commit()
    db.refresh(settings)
    return _to_settings_out(settings)


@router.get("/settings/workflows", response_model=WorkflowModeListOut)
def list_workflow_modes(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.INTELLIGENCE_VIEW))],
) -> WorkflowModeListOut:
    settings = _get_or_create_settings(db)
    db.commit()
    overrides = {
        o.workflow: o
        for o in db.scalars(
            select(IntelligenceWorkflowMode).where(
                IntelligenceWorkflowMode.is_active.is_(True)
            )
        ).all()
    }
    items = []
    for wf in WORKFLOWS:
        override = overrides.get(wf)
        effective = resolve_effective_mode(db, wf)
        items.append(_to_workflow_out(wf, settings, override, effective))
    return WorkflowModeListOut(items=items)


@router.patch("/settings/workflows/{workflow}", response_model=WorkflowModeOut)
def update_workflow_mode(
    workflow: str,
    body: UpdateWorkflowModeIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.INTELLIGENCE_MANAGE))],
) -> WorkflowModeOut:
    _validate_workflow(workflow)
    _validate_mode(body.mode)
    if body.mode == "autonomous" and body.is_active and not body.acknowledged_autonomous:
        raise AppError(
            "autonomous_requires_acknowledgement",
            "Selecting Autonomous requires explicit acknowledgement",
            422,
        )
    if not body.reason or not body.reason.strip():
        raise AppError("reason_required", "A reason is required", 422)

    settings = _get_or_create_settings(db)
    existing = db.scalar(
        select(IntelligenceWorkflowMode).where(
            IntelligenceWorkflowMode.workflow == workflow
        )
    )
    if existing and existing.row_version != body.row_version:
        raise AppError(
            "record_changed",
            f"Workflow override changed (current row_version {existing.row_version})",
            409,
            {"current_row_version": existing.row_version},
        )
    if existing is None and body.row_version is not None:
        raise AppError(
            "record_changed",
            "No existing override; omit row_version for create",
            409,
        )
    previous_mode = existing.mode if existing else settings.default_mode

    if existing is None:
        existing = IntelligenceWorkflowMode(
            id=uuid.uuid4(),
            workflow=workflow,
            mode=body.mode,
            is_active=body.is_active,
            effective_from=body.effective_from or datetime.now(timezone.utc),
            row_version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(existing)
    else:
        existing.mode = body.mode
        existing.is_active = body.is_active
        if body.effective_from:
            existing.effective_from = body.effective_from
        existing.row_version += 1
        existing.updated_at = datetime.now(timezone.utc)

    audit = write_audit(
        db, user,
        entity_type="intelligence_workflow_mode",
        entity_id=existing.id,
        action="intelligence.workflow_mode.update",
        old_value={"workflow": workflow, "previous_mode": previous_mode},
        new_value={
            "workflow": workflow,
            "new_mode": body.mode,
            "is_active": body.is_active,
        },
        reason=body.reason,
    )
    db.flush()
    record_mode_change(
        db, user,
        workflow=workflow,
        previous_mode=previous_mode,
        new_mode=body.mode,
        reason=body.reason,
        effective_from=body.effective_from or datetime.now(timezone.utc),
        audit_id=getattr(audit, "id", None),
    )
    db.commit()
    db.refresh(existing)
    effective = resolve_effective_mode(db, workflow)
    return _to_workflow_out(workflow, settings, existing, effective)


@router.get("/settings/change-log", response_model=ModeChangeLogListOut)
def list_change_log(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.INTELLIGENCE_VIEW))],
    limit: int = Query(50, ge=1, le=500),
) -> ModeChangeLogListOut:
    rows = list(db.scalars(
        select(IntelligenceModeChangeLog)
        .order_by(IntelligenceModeChangeLog.changed_at.desc())
        .limit(limit)
    ).all())
    return ModeChangeLogListOut(
        items=[ModeChangeLogOut.model_validate(r, from_attributes=True) for r in rows]
    )
