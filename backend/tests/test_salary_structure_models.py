"""Milestone 3 Stage A — schema tests for ten_0027.

Verifies the salary-structure migration at the DB level: table existence,
CHECK constraints, partial unique indexes, FK deletion policies, and the
additive columns on existing tables. Uses raw SQL through tenant_engine_admin
so the DB schema is tested directly (not the ORM mapping).
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


# ----------------------------- fixtures -----------------------------

@pytest.fixture()
def db(tenant_engine_admin):
    """Per-test transaction on the session tenant; rolled back at teardown."""
    conn = tenant_engine_admin.connect()
    tx = conn.begin()
    try:
        yield conn
    finally:
        tx.rollback()
        conn.close()


# ----------------------------- helpers -----------------------------

def _mk_employee(db, code: str | None = None) -> uuid.UUID:
    eid = uuid.uuid4()
    code = code or f"E{eid.hex[:10]}"
    db.execute(text("""
        INSERT INTO employee (
            id, employee_code, first_name, last_name, hire_date,
            employee_type, pay_basis, pay_frequency,
            overtime_eligible, clocks, uif_exempt,
            medical_aid_dependants, medical_scheme_members, row_version
        ) VALUES (
            :id, :code, 'Test', 'User', CURRENT_DATE,
            'monthly', 'monthly', 'monthly',
            TRUE, TRUE, FALSE, 0, 0, 1
        )
    """), {"id": eid, "code": code})
    return eid


def _mk_structure(db, *, group_id=None, version=1, is_current=True,
                  pay_basis="monthly") -> tuple[uuid.UUID, uuid.UUID]:
    sid = uuid.uuid4()
    group_id = group_id or uuid.uuid4()
    db.execute(text("""
        INSERT INTO salary_structure (
            id, structure_group_id, version_number, is_current,
            name, pay_basis, base_rate, is_active, row_version
        ) VALUES (
            :id, :gid, :ver, :cur,
            'Test Structure', :basis, 10000.00, TRUE, 1
        )
    """), {"id": sid, "gid": group_id, "ver": version,
           "cur": is_current, "basis": pay_basis})
    return sid, group_id


def _mk_assignment(db, *, employee_id, structure_id,
                   effective_from=None, status="pending",
                   effective_to=None) -> uuid.UUID:
    aid = uuid.uuid4()
    effective_from = effective_from or date.today()
    db.execute(text("""
        INSERT INTO employee_salary_structure_assignment (
            id, employee_id, structure_id, effective_from, effective_to,
            status, override_manual_ids, row_version
        ) VALUES (
            :id, :eid, :sid, :ef, :et, :st, '[]'::jsonb, 1
        )
    """), {"id": aid, "eid": employee_id, "sid": structure_id,
           "ef": effective_from, "et": effective_to, "st": status})
    return aid


def _mk_earning_type(db) -> uuid.UUID:
    etid = uuid.uuid4()
    db.execute(text("""
        INSERT INTO earning_type (
            id, name, code, calc_method, frequency,
            is_taxable, counts_for_uif, counts_for_sdl,
            proration_rule, is_system, is_active, row_version
        ) VALUES (
            :id, 'Earn', :code, 'fixed_amount', 'regular',
            TRUE, TRUE, TRUE, 'none', FALSE, TRUE, 1
        )
    """), {"id": etid, "code": f"ET{etid.hex[:8]}"})
    return etid


def _mk_deduction_type(db) -> uuid.UUID:
    dtid = uuid.uuid4()
    db.execute(text("""
        INSERT INTO deduction_type (
            id, name, code, category, priority, is_pre_tax,
            is_system, is_active, row_version
        ) VALUES (
            :id, 'Ded', :code, 'other', 100, FALSE, FALSE, TRUE, 1
        )
    """), {"id": dtid, "code": f"DT{dtid.hex[:8]}"})
    return dtid


# ----------------------------- tests -----------------------------

def test_new_tables_exist(db):
    for name in (
        "salary_structure",
        "salary_structure_component",
        "employee_salary_structure_assignment",
        "employee_salary_structure_assignment_attempt",
    ):
        present = db.scalar(text("SELECT to_regclass(:n)"),
                            {"n": f"public.{name}"})
        assert present is not None, f"table {name} missing"


def test_additive_columns_exist(db):
    expected = {
        "employee_earning": "source_assignment_id",
        "employee_deduction": "source_assignment_id",
        "employee_pay_history": "source_assignment_id",
        "payroll_change_request": "assignment_id",
    }
    for table, column in expected.items():
        ok = db.scalar(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = :t AND column_name = :c
        """), {"t": table, "c": column})
        assert ok == 1, f"{table}.{column} missing"


def test_salary_structure_check_pay_basis(db):
    with pytest.raises(IntegrityError):
        _mk_structure(db, pay_basis="weekly")


def test_salary_structure_check_version_positive(db):
    with pytest.raises(IntegrityError):
        _mk_structure(db, version=0)


def test_salary_structure_partial_unique_current(db):
    _, gid = _mk_structure(db, is_current=True)
    with pytest.raises(IntegrityError):
        _mk_structure(db, group_id=gid, version=2, is_current=True)


def test_component_check_type_exclusive(db):
    sid, _ = _mk_structure(db)
    etid = _mk_earning_type(db)
    dtid = _mk_deduction_type(db)
    with pytest.raises(IntegrityError):
        db.execute(text("""
            INSERT INTO salary_structure_component (
                id, structure_id, kind, earning_type_id, deduction_type_id,
                amount, row_version
            ) VALUES (
                :id, :sid, 'earning', :etid, :dtid, 500.00, 1
            )
        """), {"id": uuid.uuid4(), "sid": sid, "etid": etid, "dtid": dtid})


def test_component_deduction_requires_amount_no_rate(db):
    sid, _ = _mk_structure(db)
    dtid = _mk_deduction_type(db)
    with pytest.raises(IntegrityError):
        db.execute(text("""
            INSERT INTO salary_structure_component (
                id, structure_id, kind, deduction_type_id,
                amount, rate, row_version
            ) VALUES (
                :id, :sid, 'deduction', :dtid, 500.00, 10.0, 1
            )
        """), {"id": uuid.uuid4(), "sid": sid, "dtid": dtid})


def test_component_earning_requires_amount_xor_rate(db):
    sid, _ = _mk_structure(db)
    etid = _mk_earning_type(db)
    with pytest.raises(IntegrityError):
        db.execute(text("""
            INSERT INTO salary_structure_component (
                id, structure_id, kind, earning_type_id,
                amount, rate, row_version
            ) VALUES (
                :id, :sid, 'earning', :etid, NULL, NULL, 1
            )
        """), {"id": uuid.uuid4(), "sid": sid, "etid": etid})


def test_assignment_status_check(db):
    eid = _mk_employee(db)
    sid, _ = _mk_structure(db)
    with pytest.raises(IntegrityError):
        _mk_assignment(db, employee_id=eid, structure_id=sid, status="bogus")


def test_assignment_effective_range_check(db):
    eid = _mk_employee(db)
    sid, _ = _mk_structure(db)
    today = date.today()
    with pytest.raises(IntegrityError):
        _mk_assignment(
            db, employee_id=eid, structure_id=sid,
            effective_from=today, effective_to=today - timedelta(days=1),
        )


def test_assignment_partial_unique_pending(db):
    eid = _mk_employee(db)
    sid, _ = _mk_structure(db)
    _mk_assignment(db, employee_id=eid, structure_id=sid, status="pending")
    with pytest.raises(IntegrityError):
        _mk_assignment(db, employee_id=eid, structure_id=sid, status="pending")


def test_assignment_partial_unique_open_approved(db):
    eid = _mk_employee(db)
    sid, _ = _mk_structure(db)
    _mk_assignment(db, employee_id=eid, structure_id=sid, status="approved",
                   effective_to=None)
    with pytest.raises(IntegrityError):
        _mk_assignment(db, employee_id=eid, structure_id=sid, status="approved",
                       effective_to=None)


def test_attempt_failure_detail_check(db):
    eid = _mk_employee(db)
    sid, _ = _mk_structure(db)
    aid = _mk_assignment(db, employee_id=eid, structure_id=sid)
    # Failed outcome requires failure_detail non-null
    with pytest.raises(IntegrityError):
        db.execute(text("""
            INSERT INTO employee_salary_structure_assignment_attempt (
                id, assignment_id, outcome, failure_detail
            ) VALUES (:id, :aid, 'failed', NULL)
        """), {"id": uuid.uuid4(), "aid": aid})


def test_fk_restrict_on_business_fks(db):
    rows = db.execute(text("""
        SELECT conname FROM pg_constraint
        WHERE contype = 'f' AND confdeltype = 'r'
          AND conname IN (
            'fk_employee_earning_source_assignment',
            'fk_employee_deduction_source_assignment',
            'fk_employee_pay_history_source_assignment',
            'fk_payroll_change_request_assignment'
          )
    """)).fetchall()
    names = {r[0] for r in rows}
    assert names == {
        "fk_employee_earning_source_assignment",
        "fk_employee_deduction_source_assignment",
        "fk_employee_pay_history_source_assignment",
        "fk_payroll_change_request_assignment",
    }


def test_fk_set_null_on_actor_fks(db):
    # Query by (table_name, column_name) instead of constraint name:
    # Postgres truncates identifiers to 63 chars and the attempt-table FK
    # (employee_salary_structure_assignment_attempt_attempted_by_user_id_fkey)
    # is 72 chars, so its constraint name is truncated and cannot be
    # hardcoded. Referential rules live in information_schema.
    expected = [
        ("employee_salary_structure_assignment", "submitted_by_user_id"),
        ("employee_salary_structure_assignment", "decided_by_user_id"),
        ("employee_salary_structure_assignment_attempt", "attempted_by_user_id"),
    ]
    for table, column in expected:
        rule = db.scalar(text("""
            SELECT rc.delete_rule
            FROM information_schema.referential_constraints rc
            JOIN information_schema.key_column_usage kcu
              ON kcu.constraint_name = rc.constraint_name
              AND kcu.constraint_schema = rc.constraint_schema
            WHERE kcu.table_schema = 'public'
              AND kcu.table_name = :t
              AND kcu.column_name = :c
        """), {"t": table, "c": column})
        assert rule == "SET NULL", (
            f"{table}.{column} delete rule is {rule!r}, expected SET NULL"
        )

# END OF FILE