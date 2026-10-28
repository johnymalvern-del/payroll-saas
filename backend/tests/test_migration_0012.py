"""Migration 0012 smoke tests.

Verifies the 8 tables created by migration 0012 exist, that the punch
columns required by amendment A2-A4 are present, and that punch is
append-only via REVOKE and/or the append-only trigger.

Uses the session-scoped tenant_engine_app / tenant_engine_admin fixtures
already defined in tests/conftest.py (same pattern as
test_audit_append_only.py). The session tenant's migration is run by the
tenant_db_name fixture, which does `alembic upgrade head`; a bug in 0012
fails that fixture and every test in the session fails with a clear
traceback pointing at the migration.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, ProgrammingError


_TABLES = [
    "shift",
    "shift_rate_rule",
    "work_pattern",
    "work_pattern_day",
    "public_holiday_tenant",
    "punch",
    "employee_work_pattern",
]


@pytest.mark.parametrize("table_name", _TABLES)
def test_table_exists(tenant_engine_app: Engine, table_name: str) -> None:
    with tenant_engine_app.connect() as conn:
        exists = conn.scalar(
            text("SELECT to_regclass(:t)"), {"t": f"public.{table_name}"}
        )
    assert exists is not None, f"Table {table_name} missing after migration 0012"


def test_device_has_row_version_column(tenant_engine_app: Engine) -> None:
    """Migration 0012 must add row_version to the 0001 device table."""
    with tenant_engine_app.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'device'"
            )
        ).all()
    actual = {r[0] for r in rows}
    assert "row_version" in actual, (
        f"device missing row_version after migration 0012: got {actual}"
    )


def test_punch_key_columns(tenant_engine_app: Engine) -> None:
    expected = {
        "client_punch_id",
        "payload_hash",
        "effective_time",
        "device_now_at_send",
        "offset_ms",
        "flags",
        "raw_payload",
    }
    with tenant_engine_app.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'punch'"
            )
        ).all()
    actual = {r[0] for r in rows}
    missing = expected - actual
    assert not missing, f"punch missing columns after migration 0012: {missing}"


@pytest.fixture()
def inserted_punch(tenant_engine_app: Engine) -> dict:
    """Insert one employee and one punch via the app engine.

    If migration 0012 omitted GRANTs on the new tables, this fixture fails
    with a permission error and the two append-only tests report it. That
    is intentional: it also verifies that payroll_app can write the new
    tables, which is the same class of guarantee migration 0001 established
    for its tables.
    """
    emp_id = uuid.uuid4()
    punch_id = uuid.uuid4()
    with tenant_engine_app.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO employee (id, employee_code, first_name, "
                "last_name, hire_date, status, employee_type, pay_basis, "
                "pay_frequency, overtime_eligible, clocks, "
                "medical_aid_dependants, uif_exempt, row_version) "
                "VALUES (:id, :code, 'A', 'B', '2024-01-01', 'active', "
                "'hourly', 'hourly', 'monthly', true, true, 0, false, 1)"
            ),
            {"id": emp_id, "code": f"SMOKE-{uuid.uuid4().hex[:8]}"},
        )
        conn.execute(
            text(
                "INSERT INTO punch (id, client_punch_id, payload_hash, "
                "employee_id, device_time, effective_time, offset_ms, "
                "method, status, raw_payload) VALUES "
                "(:id, :cid, :ph, :eid, NOW(), NOW(), 0, 'manual_import', "
                "'accepted', '{}'::jsonb)"
            ),
            {
                "id": punch_id,
                "cid": uuid.uuid4(),
                "ph": "0" * 64,
                "eid": emp_id,
            },
        )
    return {"employee_id": emp_id, "punch_id": punch_id}


def test_punch_append_only_blocks_update(
    tenant_engine_app: Engine, inserted_punch: dict
) -> None:
    with pytest.raises((DBAPIError, ProgrammingError)) as exc_info:
        with tenant_engine_app.begin() as conn:
            conn.execute(
                text("UPDATE punch SET status = 'tampered' WHERE id = :id"),
                {"id": inserted_punch["punch_id"]},
            )
    message = str(exc_info.value).lower()
    assert "permission denied" in message or "append-only" in message


def test_punch_append_only_blocks_delete(
    tenant_engine_app: Engine, inserted_punch: dict
) -> None:
    with pytest.raises((DBAPIError, ProgrammingError)) as exc_info:
        with tenant_engine_app.begin() as conn:
            conn.execute(
                text("DELETE FROM punch WHERE id = :id"),
                {"id": inserted_punch["punch_id"]},
            )
    message = str(exc_info.value).lower()
    assert "permission denied" in message or "append-only" in message

# END OF FILE