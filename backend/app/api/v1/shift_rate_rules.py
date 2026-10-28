'''Shift rate rule endpoints (Chapter 2A).'''
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.shift_rate_rules_schemas import (
    ShiftRateRuleCreateIn,
    ShiftRateRuleListOut,
    ShiftRateRuleOut,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.rate_lookup import (
    validate_period_non_overlap,
    validate_tier_structure,
)
from app.db.tenant.models.attendance import Shift, ShiftRateRule
from app.db.tenant.models.platform import AuditLog
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix='/shifts/{shift_id}/rate-rules', tags=['shift-rate-rules'])


def _to_out(r: ShiftRateRule) -> ShiftRateRuleOut:
    return ShiftRateRuleOut(
        id=r.id, shift_id=r.shift_id, day_type=r.day_type, kind=r.kind,
        tier=r.tier, tier_up_to_minutes=r.tier_up_to_minutes,
        method=r.method, value=r.value, flat_unit=r.flat_unit,
        effective_from=r.effective_from, effective_to=r.effective_to,
    )


def _shift_or_404(db: Any, shift_id: uuid.UUID) -> Shift:
    s = db.get(Shift, shift_id)
    if s is None:
        raise AppError('record_not_found', 'Shift not found', 404)
    return s


@router.get('', response_model=ShiftRateRuleListOut)
def list_rate_rules(
    shift_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
    day_type: str | None = Query(None),
    kind: str | None = Query(None),
    effective_on: date | None = Query(None),
) -> ShiftRateRuleListOut:
    _shift_or_404(db, shift_id)
    q = select(ShiftRateRule).where(ShiftRateRule.shift_id == shift_id)
    if day_type is not None:
        q = q.where(ShiftRateRule.day_type == day_type)
    if kind is not None:
        q = q.where(ShiftRateRule.kind == kind)
    if effective_on is not None:
        q = q.where(ShiftRateRule.effective_from <= effective_on)
        q = q.where((ShiftRateRule.effective_to.is_(None)) | (ShiftRateRule.effective_to >= effective_on))
    q = q.order_by(ShiftRateRule.day_type, ShiftRateRule.kind, ShiftRateRule.tier, ShiftRateRule.effective_from)
    rows = list(db.scalars(q).all())
    return ShiftRateRuleListOut(items=[_to_out(r) for r in rows])


@router.post('', response_model=ShiftRateRuleOut, status_code=status.HTTP_201_CREATED)
def create_rate_rule(
    shift_id: uuid.UUID,
    payload: ShiftRateRuleCreateIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> ShiftRateRuleOut:
    _shift_or_404(db, shift_id)
    siblings = list(db.scalars(
        select(ShiftRateRule).where(
            ShiftRateRule.shift_id == shift_id,
            ShiftRateRule.day_type == payload.day_type,
            ShiftRateRule.kind == payload.kind,
        )
    ).all())
    same_period = [r for r in siblings if r.effective_from == payload.effective_from and r.effective_to == payload.effective_to]
    validate_period_non_overlap(
        payload.effective_from,
        payload.effective_to,
        [(r.effective_from, r.effective_to) for r in siblings if not (r.effective_from == payload.effective_from and r.effective_to == payload.effective_to)],
    )
    proposed_set = [r for r in same_period] + [
        type('R', (), {'tier': payload.tier, 'tier_up_to_minutes': payload.tier_up_to_minutes})
    ]
    validate_tier_structure(proposed_set)
    rule = ShiftRateRule(
        shift_id=shift_id, day_type=payload.day_type, kind=payload.kind,
        tier=payload.tier, tier_up_to_minutes=payload.tier_up_to_minutes,
        method=payload.method, value=payload.value, flat_unit=payload.flat_unit,
        effective_from=payload.effective_from, effective_to=payload.effective_to,
    )
    db.add(rule)
    db.flush()
    snap = _to_out(rule).model_dump(mode='json')
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user, 'id', None), actor_role=getattr(user, 'role', None), entity_type='shift_rate_rule', entity_id=str(rule.id), action='shift_rate_rule.create', old_value=None, new_value=redact_for_audit(snap)))
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.delete('/{rule_id}', status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
def delete_rate_rule(
    shift_id: uuid.UUID,
    rule_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SHIFT_CONFIGURE))],
) -> Response:
    _shift_or_404(db, shift_id)
    rule = db.get(ShiftRateRule, rule_id)
    if rule is None or rule.shift_id != shift_id:
        raise AppError('record_not_found', 'Rate rule not found', 404)
    if rule.effective_from <= date.today():
        raise AppError('rate_rule_in_use', 'Only future-dated rate rules may be deleted; end this rule with effective_to instead', 409, {'effective_from': rule.effective_from.isoformat()})
    old_snap = _to_out(rule).model_dump(mode='json')
    db.delete(rule)
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user, 'id', None), actor_role=getattr(user, 'role', None), entity_type='shift_rate_rule', entity_id=str(rule_id), action='shift_rate_rule.delete', old_value=redact_for_audit(old_snap), new_value=None))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# END OF FILE
