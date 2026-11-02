"""Reason-code list endpoint (B-12).

GET /attendance/reason-codes returns the current allow-list for
adjustment and exception-resolution reason codes. The list is read
from `_current_reason_codes` (the same function `_validate_reason`
in exceptions.py calls), so the API response can never diverge from
the validator.

Permission: ATTENDANCE_VIEW (read-only; the actual write endpoints
POST /attendance/adjustments and POST /attendance/exceptions/*/resolve
still require ATTENDANCE_ADJUST).

`requires_note` is derived, not stored: `other` is the only code that
requires a note today (>= 10 chars, per _validate_reason). Adding new
codes that require notes is a one-line change here.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import TenantDbDep
from app.api.v1.exceptions import _current_reason_codes
from app.core.permissions import Permission, require_permission

router = APIRouter(
    prefix="/attendance/reason-codes",
    tags=["attendance-reason-codes"],
)

_DEFAULT_LABELS = {
    "device_down": "Device down",
    "forgot_clock": "Forgot clock",
    "approved_site_work": "Approved site work",
    "system_correction": "System correction",
    "other": "Other",
}

# Codes we know always sort first, in this order. Anything else a tenant
# adds goes after these, but `other` (when present) is forced last.
_KNOWN_ORDER = (
    "device_down",
    "forgot_clock",
    "approved_site_work",
    "system_correction",
)


class ReasonCodeOut(BaseModel):
    code: str
    label: str
    requires_note: bool


class ReasonCodeListOut(BaseModel):
    items: list[ReasonCodeOut]


def _label_for(code: str) -> str:
    if code in _DEFAULT_LABELS:
        return _DEFAULT_LABELS[code]
    return code.replace("_", " ").title()


def _order_codes(codes: tuple[str, ...]) -> list[str]:
    present = set(codes)
    head = [c for c in _KNOWN_ORDER if c in present]
    middle = [c for c in codes if c not in _KNOWN_ORDER and c != "other"]
    tail = ["other"] if "other" in present else []
    return head + middle + tail


@router.get("", response_model=ReasonCodeListOut)
def list_reason_codes(
    db: TenantDbDep,
    _user: Annotated[Any, Depends(require_permission(Permission.ATTENDANCE_VIEW))],
) -> ReasonCodeListOut:
    codes = _current_reason_codes(db)
    ordered = _order_codes(codes)
    return ReasonCodeListOut(
        items=[
            ReasonCodeOut(
                code=c,
                label=_label_for(c),
                requires_note=(c == "other"),
            )
            for c in ordered
        ]
    )