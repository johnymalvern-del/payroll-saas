"""Phase 1A — audit patch, permissions patch, service."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BE = ROOT / "backend"

# ---------- 1. payroll_audit.py: add actor_system kwarg + return AuditLog ----------
audit = BE / "app" / "services" / "payroll_audit.py"
s = audit.read_text(encoding="utf-8")

if "actor_system" in s:
    print("payroll_audit.py: actor_system already present")
else:
    old = '''def write_audit(
    db: Session,
    user: Any,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    old_value: dict | None = None,
    new_value: dict | None = None,
    reason: str | None = None,
) -> None:
    from app.db.tenant.models.platform import AuditLog

    cols = {c.name for c in AuditLog.__table__.columns}
    kwargs: dict[str, Any] = {}
    for k, v in (
        ("actor_user_id", getattr(user, "id", None)),
        ("actor_role", getattr(user, "role", None)),
        ("entity_type", entity_type),
        ("entity_id", entity_id),
        ("action", action),
        ("old_value", old_value),
        ("new_value", new_value),
        ("reason", reason),
        ("occurred_at", datetime.now(timezone.utc)),
    ):
        if k in cols:
            kwargs[k] = v
    db.add(AuditLog(**kwargs))
'''
    new = '''def write_audit(
    db: Session,
    user: Any,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    old_value: dict | None = None,
    new_value: dict | None = None,
    reason: str | None = None,
    actor_system: bool = False,
) -> "AuditLog":
    """Append an audit row.

    If actor_system=True, actor_role is set to 'system' and actor_user_id is
    None. That satisfies Phase 1A's "service identity distinguishable from
    humans" requirement without a schema change (Phase 1E may add an
    explicit actor_system column). The created AuditLog row is returned so
    callers can link downstream records (e.g. intelligence_mode_change_log).
    """
    from app.db.tenant.models.platform import AuditLog

    cols = {c.name for c in AuditLog.__table__.columns}
    kwargs: dict[str, Any] = {}
    for k, v in (
        ("actor_user_id", None if actor_system else getattr(user, "id", None)),
        ("actor_role", "system" if actor_system else getattr(user, "role", None)),
        ("entity_type", entity_type),
        ("entity_id", entity_id),
        ("action", action),
        ("old_value", old_value),
        ("new_value", new_value),
        ("reason", reason),
        ("occurred_at", datetime.now(timezone.utc)),
    ):
        if k in cols:
            kwargs[k] = v
    row = AuditLog(**kwargs)
    db.add(row)
    return row
'''
    if old not in s:
        raise SystemExit("FATAL: write_audit block not matched — inspect file")
    s = s.replace(old, new, 1)
    audit.write_text(s, encoding="utf-8")
    print("payroll_audit.py: actor_system kwarg + AuditLog return added")

# ---------- 2. permissions.py: 2 enum + 3 role grants ----------
perm = BE / "app" / "core" / "permissions.py"
s = perm.read_text(encoding="utf-8")

if "INTELLIGENCE_VIEW" in s:
    print("permissions.py: already present")
else:
    # Add enum values after ATTENDANCE_VIEW
    old_enum = "    ATTENDANCE_VIEW = \"attendance_view\"\n"
    new_enum = (
        "    ATTENDANCE_VIEW = \"attendance_view\"\n"
        "    INTELLIGENCE_VIEW = \"intelligence_view\"\n"
        "    INTELLIGENCE_MANAGE = \"intelligence_manage\"\n"
    )
    if old_enum not in s:
        raise SystemExit("FATAL: ATTENDANCE_VIEW enum line not found")
    s = s.replace(old_enum, new_enum, 1)
    print("permissions.py: 2 enum values added")

    # hr: add INTELLIGENCE_VIEW (before ORG_VIEW line inside hr block)
    old_hr = '''    "hr": frozenset({
        Permission.SELF_VIEW,
        Permission.SELF_SUBMIT,
        Permission.PAYSLIP_VIEW,
        Permission.LEAVE_APPROVE,
        Permission.SICK_NOTE_VIEW,
        Permission.ATTENDANCE_ADJUST,
        Permission.OVERTIME_APPROVE,
        Permission.EXCEPTION_RESOLVE,
        Permission.ADVANCE_DECIDE,
        Permission.GRIEVANCE_HANDLE,
        Permission.PAY_RATE_REQUEST,
        Permission.PAY_RATE_VIEW,
        Permission.BANK_DETAIL_REQUEST,
        Permission.PAYROLL_PREVIEW,
        Permission.EMPLOYEE_CRUD,
        Permission.ORG_VIEW,
        Permission.ORG_MANAGE,
        Permission.ATTENDANCE_VIEW,
    }),
'''
    new_hr = old_hr.replace(
        "        Permission.ATTENDANCE_VIEW,\n    }),",
        "        Permission.ATTENDANCE_VIEW,\n        Permission.INTELLIGENCE_VIEW,\n    }),",
    )
    if old_hr not in s:
        raise SystemExit("FATAL: hr block not matched — inspect permissions.py")
    s = s.replace(old_hr, new_hr, 1)
    print("permissions.py: hr gains INTELLIGENCE_VIEW")

    # payroll_admin: add INTELLIGENCE_VIEW + INTELLIGENCE_MANAGE
    # Need to find the payroll_admin block dynamically and append before its closing.
    pa_start = s.find('    "payroll_admin": frozenset({')
    if pa_start < 0:
        raise SystemExit("FATAL: payroll_admin block start not found")
    pa_end = s.find("\n    }),", pa_start)
    if pa_end < 0:
        raise SystemExit("FATAL: payroll_admin block end not found")
    pa_block = s[pa_start:pa_end]
    if "INTELLIGENCE_MANAGE" in pa_block:
        print("permissions.py: payroll_admin already has INTELLIGENCE_MANAGE")
    else:
        s = (
            s[:pa_end]
            + "\n        Permission.INTELLIGENCE_VIEW,"
            + "\n        Permission.INTELLIGENCE_MANAGE,"
            + s[pa_end:]
        )
        print("permissions.py: payroll_admin gains INTELLIGENCE_VIEW + INTELLIGENCE_MANAGE")

    # auditor: add INTELLIGENCE_VIEW only
    au_start = s.find('    "auditor": frozenset({')
    if au_start < 0:
        raise SystemExit("FATAL: auditor block start not found")
    au_end = s.find("\n    }),", au_start)
    if au_end < 0:
        raise SystemExit("FATAL: auditor block end not found")
    au_block = s[au_start:au_end]
    if "INTELLIGENCE_VIEW" in au_block:
        print("permissions.py: auditor already has INTELLIGENCE_VIEW")
    else:
        s = (
            s[:au_end]
            + "\n        Permission.INTELLIGENCE_VIEW,"
            + s[au_end:]
        )
        print("permissions.py: auditor gains INTELLIGENCE_VIEW")

    perm.write_text(s, encoding="utf-8")

# ---------- 3. test_permissions.py: 2 matrix rows ----------
tp = BE / "tests" / "test_permissions.py"
s = tp.read_text(encoding="utf-8")

if "INTELLIGENCE_VIEW" in s:
    print("test_permissions.py: already present")
else:
    # Insert after ATTENDANCE_VIEW row in SECTION_6_MATRIX
    old_row = (
        '    Permission.ATTENDANCE_VIEW: {"employee": True, "manager": True, '
        '"hr": True, "payroll_admin": True, "auditor": False},\n'
    )
    new_rows = old_row + (
        '    Permission.INTELLIGENCE_VIEW: {"employee": False, "manager": False, '
        '"hr": True, "payroll_admin": True, "auditor": True},\n'
        '    Permission.INTELLIGENCE_MANAGE: {"employee": False, "manager": False, '
        '"hr": False, "payroll_admin": True, "auditor": False},\n'
    )
    if old_row not in s:
        # Try a looser fallback: find the ATTENDANCE_VIEW line
        m = re.search(r"    Permission\.ATTENDANCE_VIEW:[^\n]*\n", s)
        if not m:
            raise SystemExit("FATAL: ATTENDANCE_VIEW row not found in SECTION_6_MATRIX")
        s = s[:m.end()] + (
            '    Permission.INTELLIGENCE_VIEW: {"employee": False, "manager": False, '
            '"hr": True, "payroll_admin": True, "auditor": True},\n'
            '    Permission.INTELLIGENCE_MANAGE: {"employee": False, "manager": False, '
            '"hr": False, "payroll_admin": True, "auditor": False},\n'
        ) + s[m.end():]
        print("test_permissions.py: 2 rows appended (fallback)")
    else:
        s = s.replace(old_row, new_rows, 1)
        print("test_permissions.py: 2 rows appended")
    tp.write_text(s, encoding="utf-8")

# ---------- 4. service ----------
svc = BE / "app" / "services" / "intelligence_service.py"
svc.write_text('''"""Intelligence service — Phase 1A foundation.

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
''', encoding="utf-8")
print("wrote backend/app/services/intelligence_service.py")

print("\nP1A stage 2 complete.")