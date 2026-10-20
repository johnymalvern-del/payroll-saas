"""Prove that the tenant audit_log cannot be modified (privileges + trigger)."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, ProgrammingError


def test_app_can_insert_audit_row(tenant_engine_app: Engine, inserted_audit_row: str) -> None:
    with tenant_engine_app.connect() as conn:
        count = conn.scalar(
            text("SELECT count(*) FROM audit_log WHERE id = :id"), {"id": inserted_audit_row}
        )
    assert count == 1


def test_app_role_cannot_update_audit_log(
    tenant_engine_app: Engine, inserted_audit_row: str
) -> None:
    with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
        with tenant_engine_app.begin() as conn:
            conn.execute(
                text("UPDATE audit_log SET action = 'tampered' WHERE id = :id"),
                {"id": inserted_audit_row},
            )
    message = str(exc_info.value).lower()
    assert "permission denied" in message or "append-only" in message


def test_app_role_cannot_delete_audit_log(
    tenant_engine_app: Engine, inserted_audit_row: str
) -> None:
    with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
        with tenant_engine_app.begin() as conn:
            conn.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": inserted_audit_row})
    message = str(exc_info.value).lower()
    assert "permission denied" in message or "append-only" in message


def test_trigger_blocks_update_even_when_granted(
    tenant_engine_admin: Engine, tenant_engine_app: Engine, inserted_audit_row: str
) -> None:
    """Even if someone grants UPDATE, the trigger rejects it. Defense in depth."""
    with tenant_engine_admin.begin() as conn:
        conn.execute(text("GRANT UPDATE ON audit_log TO payroll_app"))
    try:
        with pytest.raises((DBAPIError, ProgrammingError)) as exc_info:
            with tenant_engine_app.begin() as conn:
                conn.execute(
                    text("UPDATE audit_log SET action = 'tampered' WHERE id = :id"),
                    {"id": inserted_audit_row},
                )
        assert "append-only" in str(exc_info.value).lower()
    finally:
        with tenant_engine_admin.begin() as conn:
            conn.execute(text("REVOKE UPDATE ON audit_log FROM payroll_app"))


def test_trigger_blocks_delete_even_when_granted(
    tenant_engine_admin: Engine, tenant_engine_app: Engine, inserted_audit_row: str
) -> None:
    with tenant_engine_admin.begin() as conn:
        conn.execute(text("GRANT DELETE ON audit_log TO payroll_app"))
    try:
        with pytest.raises((DBAPIError, ProgrammingError)) as exc_info:
            with tenant_engine_app.begin() as conn:
                conn.execute(
                    text("DELETE FROM audit_log WHERE id = :id"), {"id": inserted_audit_row}
                )
        assert "append-only" in str(exc_info.value).lower()
    finally:
        with tenant_engine_admin.begin() as conn:
            conn.execute(text("REVOKE DELETE ON audit_log FROM payroll_app"))