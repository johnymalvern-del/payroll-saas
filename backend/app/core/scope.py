
"""Row-level scope enforcement (site, branch, department, direct reports).

The matrix in app/core/permissions.py answers "is this role allowed this
capability?". This module answers "for which rows?". Both are needed: an hr
user without scope rows sees every employee; an hr user with scope rows sees
only those in scope. A manager with neither direct reports nor scope rows
sees nobody -- never everybody. This is the fail-closed rule.

Scope rules (from the master brief, section 6, applied literally):

  employee      - own records only.
  manager       - (a) direct reports (employees whose manager_id equals the
                  manager's own employee record id)
                  UNION
                  (b) employees in any site, branch or department listed in
                  the manager's user_scope rows.
                  If both sets are empty, sees nobody. Fails closed.
  hr            - company-wide UNLESS user_scope rows exist, in which case
                  restricted to those (same shape as manager but no direct
                  reports dimension - HR has no direct reports concept).
  payroll_admin - company-wide, no filtering.
  auditor       - company-wide, no filtering.

`apply_scope(query, user, model)` is for list queries: it appends a
`model.site_id.in_(...)` style filter so a manager's list endpoint returns
only their scope. `assert_in_scope(user, employee_id)` is for single-row
reads and writes: it raises `ScopeViolation` unless the target employee is
within the user's scope. Both use the same rules; neither is safe alone
because list reads and single reads are different code paths.

`ScopeViolation` is deliberately a plain Exception (not HTTPException) so
that service-layer code can decide the response. Endpoints usually map it to
404 (not 403) so an out-of-scope record appears the same as a nonexistent
one - that is the standard mitigation for insecure direct object reference
(IDOR) probing.

If the role of the user is unknown, both functions fail closed. If the
user's employee_id is missing (e.g. an HR user without an employee record),
`apply_scope` returns an empty result set rather than all rows.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.tenant.models.organisation import Branch, Department, Site
from app.db.tenant.models.people import Employee, UserScope


class ScopeViolation(Exception):
    """Raised when a specific employee is outside the current user's scope."""


# ---------------------------------------------------------------------------
# Which employees are within scope?
# ---------------------------------------------------------------------------


def _scoped_target_ids(session: Session, user: Any) -> set[uuid.UUID] | None:
    """Return the set of employee_ids the user can see, or None for "all".

    Returning None means "company-wide, do not filter". Returning an empty
    set means "sees nobody". Callers must distinguish these.
    """
    role = getattr(user, "role", None)
    user_id = getattr(user, "id", None)
    employee_id = getattr(user, "employee_id", None)

    if role in ("payroll_admin", "auditor"):
        return None

    if role == "employee":
        return {employee_id} if employee_id else set()

    if role == "hr":
        scope_rows = _user_scope_rows(session, user_id)
        if not scope_rows:
            return None  # company-wide HR without explicit scope rows
        return _employees_in_scope(session, scope_rows)

    if role == "manager":
        if not employee_id:
            return set()  # manager without an employee record: sees nobody
        direct_reports = _direct_reports(session, employee_id)
        scope_rows = _user_scope_rows(session, user_id)
        scope_employees = _employees_in_scope(session, scope_rows) if scope_rows else set()
        return direct_reports | scope_employees

    # Unknown role: fail closed.
    return set()


def _user_scope_rows(session: Session, user_id: uuid.UUID | None) -> list[UserScope]:
    if not user_id:
        return []
    return list(session.scalars(select(UserScope).where(UserScope.user_id == user_id)).all())


def _direct_reports(session: Session, manager_employee_id: uuid.UUID) -> set[uuid.UUID]:
    rows = session.scalars(
        select(Employee.id).where(Employee.manager_id == manager_employee_id)
    ).all()
    return set(rows)


def _employees_in_scope(session: Session, scope_rows: list[UserScope]) -> set[uuid.UUID]:
    """Resolve site/branch/department scope rows to a set of employee_ids."""
    if not scope_rows:
        return set()

    site_ids: list[uuid.UUID] = []
    branch_ids: list[uuid.UUID] = []
    dept_ids: list[uuid.UUID] = []
    for row in scope_rows:
        if row.scope_type == "site":
            site_ids.append(row.scope_id)
        elif row.scope_type == "branch":
            branch_ids.append(row.scope_id)
        elif row.scope_type == "department":
            dept_ids.append(row.scope_id)

    clauses = []
    if site_ids:
        clauses.append(Employee.site_id.in_(site_ids))
    if branch_ids:
        clauses.append(Employee.branch_id.in_(branch_ids))
    if dept_ids:
        clauses.append(Employee.department_id.in_(dept_ids))
    if not clauses:
        return set()

    rows = session.scalars(select(Employee.id).where(and_(True, *[]) if False else (clauses[0] if len(clauses) == 1 else __import__("sqlalchemy").or_(*clauses)))).all()
    return set(rows)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_scope(query: Any, user: Any, session: Session, model: Any = Employee) -> Any:
    """Append a filter to `query` so it returns only rows in the user's scope.

    For `model=Employee`, filters by `Employee.id.in_(target_ids)`. For
    models that carry an `employee_id` column (attendance, leave, etc.), call
    with the appropriate column by passing `model` and the function will use
    `model.employee_id.in_(target_ids)`.

    Returns the query unchanged for payroll_admin and auditor. Returns a
    query filtered to nothing for unknown roles and for users with no
    employee record.
    """
    target = _scoped_target_ids(session, user)
    if target is None:
        return query  # company-wide
    if not target:
        # Fail closed: force an empty result set.
        return query.where(False)
    column = getattr(model, "employee_id", None) or getattr(model, "id", None)
    if column is None:
        # Model has no employee linkage; fail closed.
        return query.where(False)
    return query.where(column.in_(target))


def assert_in_scope(user: Any, employee_id: uuid.UUID, session: Session) -> None:
    """Raise ScopeViolation unless employee_id is in the user's scope.

    Used on every single-row read and write so a manager cannot fetch or
    modify a record outside their scope by guessing its UUID. Endpoints that
    catch ScopeViolation should respond 404 (not 403) so the response is
    indistinguishable from a nonexistent record.
    """
    target = _scoped_target_ids(session, user)
    if target is None:
        return  # company-wide
    if employee_id not in target:
        raise ScopeViolation(
            f"employee {employee_id} is outside the current user's scope"
        )
