"""Permission matrix and enforcement dependency.

Every capability an endpoint exposes must be enumerated here as a `Permission`
and mapped to the roles allowed to exercise it. The matrix mirrors section 6
of the master brief. Endpoints enforce via `require_permission(perm)`; the
matrix test (tests/test_permissions.py) independently re-declares the same
matrix and asserts the code agrees with it.

Two separation-of-duty rules are enforced by the matrix itself:

  * PAY_RATE_REQUEST  is granted to `hr` only.
    PAY_RATE_APPROVE  is granted to `payroll_admin` only.
    PAY_RATE_VIEW     is granted to `hr`, `payroll_admin` and `auditor`.
  * BANK_DETAIL_REQUEST is granted to `hr` only.
    BANK_DETAIL_APPROVE is granted to `payroll_admin` only.

Scope (site, branch, department filters) is NOT a permission; it is handled
in app/core/scope.py.

1C.5 adds ORG_VIEW (organisation read: branches, sites, departments) and
ORG_MANAGE (organisation write). Per the roadmap:
  ORG_VIEW  - employee, manager, hr, payroll_admin, auditor.
  ORG_MANAGE- hr, payroll_admin.
The scope rules decide *which* branches each role sees; the permission only
decides whether the role may call the endpoint at all.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status

from app.core.auth_deps import get_current_user


class Permission(str, Enum):
    SELF_VIEW = "self_view"
    SELF_SUBMIT = "self_submit"
    PAYSLIP_VIEW = "payslip_view"

    LEAVE_APPROVE = "leave_approve"
    SICK_NOTE_VIEW = "sick_note_view"
    ATTENDANCE_ADJUST = "attendance_adjust"
    OVERTIME_APPROVE = "overtime_approve"
    EXCEPTION_RESOLVE = "exception_resolve"
    ADVANCE_DECIDE = "advance_decide"
    GRIEVANCE_HANDLE = "grievance_handle"

    PAY_RATE_REQUEST = "pay_rate_request"
    PAY_RATE_APPROVE = "pay_rate_approve"
    PAY_RATE_VIEW = "pay_rate_view"
    BANK_DETAIL_REQUEST = "bank_detail_request"
    BANK_DETAIL_APPROVE = "bank_detail_approve"

    SHIFT_CONFIGURE = "shift_configure"
    PAYROLL_PREVIEW = "payroll_preview"
    PAYROLL_FINALISE = "payroll_finalise"
    PAYROLL_REOPEN = "payroll_reopen"

    AUDIT_VIEW = "audit_view"
    USER_MANAGE = "user_manage"
    EMPLOYEE_CRUD = "employee_crud"

    ORG_VIEW = "org_view"
    ORG_MANAGE = "org_manage"


# Role -> set of permissions. Mirrors section 6 of the master brief.
# Any change here MUST be mirrored in tests/test_permissions.py's own matrix.
ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "employee": frozenset({
        Permission.SELF_VIEW,
        Permission.SELF_SUBMIT,
        Permission.PAYSLIP_VIEW,
        Permission.ORG_VIEW,
    }),
    "manager": frozenset({
        Permission.SELF_VIEW,
        Permission.SELF_SUBMIT,
        Permission.PAYSLIP_VIEW,
        Permission.LEAVE_APPROVE,
        Permission.ATTENDANCE_ADJUST,
        Permission.OVERTIME_APPROVE,
        Permission.EXCEPTION_RESOLVE,
        Permission.ORG_VIEW,
    }),
    "hr": frozenset({
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
    }),
    "payroll_admin": frozenset({
        Permission.SELF_VIEW,
        Permission.SELF_SUBMIT,
        Permission.PAYSLIP_VIEW,
        Permission.LEAVE_APPROVE,
        Permission.SICK_NOTE_VIEW,
        Permission.ATTENDANCE_ADJUST,
        Permission.OVERTIME_APPROVE,
        Permission.EXCEPTION_RESOLVE,
        Permission.ADVANCE_DECIDE,
        Permission.PAY_RATE_APPROVE,
        Permission.PAY_RATE_VIEW,
        Permission.BANK_DETAIL_APPROVE,
        Permission.SHIFT_CONFIGURE,
        Permission.PAYROLL_PREVIEW,
        Permission.PAYROLL_FINALISE,
        Permission.PAYROLL_REOPEN,
        Permission.AUDIT_VIEW,
        Permission.USER_MANAGE,
        Permission.EMPLOYEE_CRUD,
        Permission.ORG_VIEW,
        Permission.ORG_MANAGE,
    }),
    "auditor": frozenset({
        Permission.PAYSLIP_VIEW,
        Permission.AUDIT_VIEW,
        Permission.ORG_VIEW,
        Permission.PAY_RATE_VIEW,
    }),
}


class PermissionDenied(HTTPException):
    def __init__(self, permission: Permission) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden", "required_permission": permission.value},
        )


def check_permission(user: Any, permission: Permission) -> bool:
    role = getattr(user, "role", None)
    if not role:
        return False
    perms = ROLE_PERMISSIONS.get(role)
    if perms is None:
        return False
    return permission in perms


def require_permission(permission: Permission):
    def _check(
        user: Annotated[Any, Depends(get_current_user)],
    ) -> Any:
        if not check_permission(user, permission):
            raise PermissionDenied(permission)
        return user

    return _check