"""Stage E — attempt-history immutability proof (design §5.8).

Three legs:
  1. Route introspection: no PATCH/PUT/DELETE on any path containing "attempt".
  2. AST scan of the two service modules: no `.delete(<AttemptClass>)` and no
     `setattr(<AttemptClass>, ...)` anywhere.
  3. Single-insert proof: a successful approve records exactly one 'approved'
     attempt row with the expected fields.
Plus one regression: approve must never route through the individual-CR
`_apply()` path.
"""
from __future__ import annotations

import ast
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.tenant.models.people import Employee, User
from app.db.tenant.models.pay import PayPeriod
from app.db.tenant.models.salary_structure import (
    EmployeeSalaryStructureAssignmentAttempt,
)
from app.services.salary_assignment_approve_service import approve_assignment
from app.services.salary_assignment_service import submit_assignment
from app.services.salary_structure_service import create_structure


_ATTEMPT_CLASS_NAME = "EmployeeSalaryStructureAssignmentAttempt"
_SERVICES_DIR = Path(__file__).resolve().parent.parent / "app" / "services"
_TARGET_SERVICES = (
    _SERVICES_DIR / "salary_assignment_service.py",
    _SERVICES_DIR / "salary_assignment_approve_service.py",
)


# ----------------------------- fixtures -----------------------------

@pytest.fixture()
def db(_leave_session_shared, monkeypatch):
    """Per-test session with commit redirected to flush."""
    s = _leave_session_shared
    monkeypatch.setattr(s, "commit", lambda: s.flush())
    return s


# ----------------------------- helpers -----------------------------

def _mk_user(db):
    return db.query(User).filter(User.username == "admin").one()


def _mk_approver(db):
    u = User(
        username=f"appr_{uuid.uuid4().hex[:8]}",
        password_hash="x", role="payroll_admin",
        is_active=True, must_change_password=False,
        failed_attempts=0, row_version=1,
    )
    db.add(u); db.flush()
    return u


def _mk_employee(db, *, pay_basis="monthly"):
    emp = Employee(
        employee_code=f"E{uuid.uuid4().hex[:8]}",
        first_name="T", last_name="E",
        hire_date=date.today() - timedelta(days=365),
        employee_type="monthly" if pay_basis == "monthly" else "hourly",
        pay_basis=pay_basis, pay_frequency="monthly",
        overtime_eligible=True, clocks=True, uif_exempt=False,
        medical_aid_dependants=0, medical_scheme_members=0,
        row_version=1,
    )
    db.add(emp); db.flush()
    return emp


def _mk_period(db, *, start, end, pay_date):
    p = PayPeriod(
        id=uuid.uuid4(), period_key=f"P{uuid.uuid4().hex[:6]}",
        start_date=start, end_date=end, pay_date=pay_date,
        status="closed",
        cutoff_at=__import__("datetime").datetime.utcnow(),
    )
    db.add(p); db.flush()
    return p


def _mk_valid_env(db):
    today = date.today()
    s = today + timedelta(days=10)
    e = s + timedelta(days=6)
    _mk_period(db, start=s, end=e, pay_date=e + timedelta(days=1))
    return e + timedelta(days=1)


def _mk_structure(db, *, user, pay_basis="monthly", base_rate="15000"):
    return create_structure(
        db, user, name=f"S{uuid.uuid4().hex[:6]}",
        description=None, pay_basis=pay_basis,
        base_rate=Decimal(base_rate),
        components=[],
    )


def _submit_and_approve(db, user, approver, emp, structure, effective_from):
    a = submit_assignment(
        db, user, employee_id=emp.id, structure_id=structure.id,
        effective_from=effective_from, idempotency_key=None,
        override_manual_ids=[],
    )
    return approve_assignment(db, approver, a.id)


# ----------------------------- route introspection -----------------------------

def test_no_write_routes_for_attempts():
    from app.main import app
    violations: list[str] = []
    for route in app.routes:
        path = getattr(route, "path", "") or ""
        if "attempt" not in path.lower():
            continue
        methods = getattr(route, "methods", set()) or set()
        non_read = methods - {"GET", "HEAD", "OPTIONS"}
        if non_read:
            violations.append(f"{path} {sorted(non_read)}")
    assert not violations, (
        f"Attempt paths must be read-only. Violations: {violations}"
    )


# ----------------------------- AST scan -----------------------------

def _references_attempt_class(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id == _ATTEMPT_CLASS_NAME:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr == _ATTEMPT_CLASS_NAME:
            return True
    return False


def test_ast_no_delete_or_setattr_attempt_in_services():
    violations: list[str] = []
    for path in _TARGET_SERVICES:
        assert path.exists(), f"Service file missing: {path}"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # <x>.delete(<attempt>) — arg references Attempt class
            if isinstance(func, ast.Attribute) and func.attr == "delete":
                if any(_references_attempt_class(arg) for arg in node.args):
                    violations.append(f"{path.name}:{node.lineno}: delete(attempt)")
            # setattr(<attempt>, ...) — first arg references Attempt class
            if isinstance(func, ast.Name) and func.id == "setattr":
                if node.args and _references_attempt_class(node.args[0]):
                    violations.append(f"{path.name}:{node.lineno}: setattr(attempt)")
    assert not violations, (
        "Attempt mutation calls found in service modules: " + ", ".join(violations)
    )


# ----------------------------- single-insert proof -----------------------------

def test_successful_approve_records_single_approved_attempt(db):
    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db); s = _mk_structure(db, user=user)
    d = _mk_valid_env(db)
    a = _submit_and_approve(db, user, approver, emp, s, d)
    attempts = db.scalars(select(EmployeeSalaryStructureAssignmentAttempt).where(
        EmployeeSalaryStructureAssignmentAttempt.assignment_id == a.id,
    )).all()
    assert len(attempts) == 1
    at = attempts[0]
    assert at.outcome == "approved"
    assert at.failure_detail is None
    assert at.attempted_by_user_id == approver.id
    assert at.attempted_at is not None


# ----------------------------- approve does not call _apply -----------------------------

def test_approve_does_not_call_apply(db, monkeypatch):
    """Design §5.11 Rule 3: batch approve must never invoke the individual
    CR write path."""
    from app.services import payroll_change_request as pcr
    calls: list[tuple] = []

    def trap(*args, **kwargs):
        calls.append((args, kwargs))
        return None

    monkeypatch.setattr(pcr, "_apply", trap)

    user = _mk_user(db); approver = _mk_approver(db)
    emp = _mk_employee(db); s = _mk_structure(db, user=user)
    d = _mk_valid_env(db)
    a = _submit_and_approve(db, user, approver, emp, s, d)
    assert a.status == "approved"
    assert calls == [], (
        "approve_assignment must not call payroll_change_request._apply; "
        f"observed {len(calls)} call(s)"
    )

# END OF FILE