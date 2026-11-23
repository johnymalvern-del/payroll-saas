"""Privilege and trigger guards on punch_location (ten_0030).

Companion to test_audit_append_only.py, which does the same job for
audit_log. Two properties matter here and they pull in opposite directions:

  punch_location must REJECT UPDATE -- a captured position is a historical
  fact and must not be editable.

  punch_location must ACCEPT DELETE -- that is the retention mechanism.
  Section 5 of the privacy policy deletes expired rows; if DELETE were
  blocked, the policy could not be implemented at all.

Testing both is necessary because the asymmetry is easy to "fix" wrongly in
either direction: someone tidying up the append-only pattern could revoke
DELETE, silently disabling retention; someone else could grant UPDATE to
"correct" a bad fix.

test_punch_still_rejects_update_after_ten_0030 is the other half: ten_0030
adds a column and a check constraint to punch, and nothing so far has proved
the 0012 append-only trigger survived that.

Fixture hygiene
---------------
tenant_engine_admin and tenant_engine_app are session scoped, so rows
outlive a single test. punch rows cannot be deleted by any role -- the 0012
trigger raises for everyone -- so those accumulate by design and every test
uses a unique employee code to avoid collisions.

punch_location CAN be deleted, so anything this module inserts is removed in
a finally block. Leaving rows behind would make the suite order-dependent:
a committed location row would still be there on the next run, and a test
asserting the unique constraint would hit it during fixture setup instead of
in its own body -- surfacing as an ERROR rather than a FAILED.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, ProgrammingError

APP_ROLE = "payroll_app"


def _mk_employee(engine_admin: Engine) -> str:
    """Minimal employee row; returns its id as a string."""
    emp_id = str(uuid.uuid4())
    code = f"GUARD-{uuid.uuid4().hex[:10]}"
    with engine_admin.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO employee "
                "(id, employee_code, first_name, last_name, hire_date, status, "
                " employee_type, pay_basis, pay_frequency, row_version) "
                "VALUES (:id, :code, 'G', 'Guard', '2024-01-01', 'active', "
                "        'hourly', 'hourly', 'monthly', 1)"
            ),
            {"id": emp_id, "code": code},
        )
    return emp_id


def _mk_punch(engine_admin: Engine, employee_id: str) -> str:
    """Minimal punch row; returns its id as a string.

    server_received_at, flags and created_at all have server defaults, so
    they are omitted deliberately -- that also re-tests the default that a
    previous edit accidentally removed from the model.
    """
    punch_id = str(uuid.uuid4())
    with engine_admin.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO punch "
                "(id, client_punch_id, payload_hash, employee_id, device_time, "
                " effective_time, offset_ms, method, status, raw_payload) "
                "VALUES (:id, :cpid, :ph, :emp, now(), now(), 0, "
                "        'fingerprint', 'accepted', '{}'::jsonb)"
            ),
            {
                "id": punch_id,
                "cpid": str(uuid.uuid4()),
                "ph": "0" * 64,
                "emp": employee_id,
            },
        )
    return punch_id


def _insert_location(engine_app: Engine, punch_id: str) -> str:
    loc_id = str(uuid.uuid4())
    with engine_app.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO punch_location "
                "(id, punch_id, latitude, longitude, gps_accuracy_m, "
                " distance_m, captured_at) "
                "VALUES (:id, :pid, -33.924900, 18.424100, 8.00, "
                "        19152.30, now())"
            ),
            {"id": loc_id, "pid": punch_id},
        )
    return loc_id


def _delete_location(engine_app: Engine, loc_id: str) -> None:
    with engine_app.begin() as conn:
        conn.execute(
            text("DELETE FROM punch_location WHERE id = :id"), {"id": loc_id}
        )


@pytest.fixture()
def punch_id(tenant_engine_admin: Engine) -> str:
    """A fresh punch per test, via a uniquely coded employee."""
    emp = _mk_employee(tenant_engine_admin)
    return _mk_punch(tenant_engine_admin, emp)


@pytest.fixture()
def location_id(tenant_engine_app: Engine, punch_id: str) -> str:
    """A location row inserted as the APP role, removed afterwards.

    Inserting as the app role is itself part of the assertion: it proves
    INSERT is granted. INSERT is not of interest. The cleanup runs in a
    finally so a failing test still leaves the database clean.
    """
    loc_id = _insert_location(tenant_engine_app, punch_id)
    try:
        yield loc_id
    finally:
        _delete_location(tenant_engine_app, loc_id)


# ---------------------------------------------------------------------------
# punch_location: INSERT yes, UPDATE no, DELETE yes
# ---------------------------------------------------------------------------


def test_app_can_insert_punch_location(location_id: str, tenant_engine_app: Engine) -> None:
    with tenant_engine_app.connect() as conn:
        count = conn.scalar(
            text("SELECT count(*) FROM punch_location WHERE id = :id"),
            {"id": location_id},
        )
    assert count == 1


def test_app_role_cannot_update_punch_location(
    location_id: str, tenant_engine_app: Engine
) -> None:
    with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
        with tenant_engine_app.begin() as conn:
            conn.execute(
                text("UPDATE punch_location SET latitude = 0 WHERE id = :id"),
                {"id": location_id},
            )
    message = str(exc_info.value).lower()
    assert "permission denied" in message or "insert/delete only" in message


def test_app_role_can_delete_punch_location(
    punch_id: str, tenant_engine_app: Engine
) -> None:
    """DELETE must SUCCEED. This is the retention mechanism.

    If this test ever fails with permission denied, someone has revoked
    DELETE while tidying up the append-only pattern, and section 5 of the
    privacy policy can no longer be implemented. That is a regression, not a
    hardening.
    """
    loc_id = _insert_location(tenant_engine_app, punch_id)
    try:
        with tenant_engine_app.begin() as conn:
            conn.execute(
                text("DELETE FROM punch_location WHERE id = :id"), {"id": loc_id}
            )
            remaining = conn.scalar(
                text("SELECT count(*) FROM punch_location WHERE id = :id"),
                {"id": loc_id},
            )
        assert remaining == 0
    finally:
        # Already gone on the happy path; harmless if it is not.
        _delete_location(tenant_engine_app, loc_id)


def test_trigger_blocks_location_update_even_when_granted(
    tenant_engine_admin: Engine, tenant_engine_app: Engine, location_id: str
) -> None:
    """Defense in depth: a future migration re-granting UPDATE still fails."""
    with tenant_engine_admin.begin() as conn:
        conn.execute(text(f"GRANT UPDATE ON punch_location TO {APP_ROLE}"))
    try:
        with pytest.raises((DBAPIError, ProgrammingError)) as exc_info:
            with tenant_engine_app.begin() as conn:
                conn.execute(
                    text("UPDATE punch_location SET latitude = 0 WHERE id = :id"),
                    {"id": location_id},
                )
        assert "insert/delete only" in str(exc_info.value).lower()
    finally:
        with tenant_engine_admin.begin() as conn:
            conn.execute(text(f"REVOKE UPDATE ON punch_location FROM {APP_ROLE}"))


# ---------------------------------------------------------------------------
# punch: the 0012 guard must have survived ten_0030
# ---------------------------------------------------------------------------


def test_punch_still_rejects_update_after_ten_0030(
    punch_id: str, tenant_engine_app: Engine
) -> None:
    with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
        with tenant_engine_app.begin() as conn:
            conn.execute(
                text("UPDATE punch SET distance_band = 'within' WHERE id = :id"),
                {"id": punch_id},
            )
    message = str(exc_info.value).lower()
    assert "permission denied" in message or "append-only" in message


def test_punch_still_rejects_delete_after_ten_0030(
    punch_id: str, tenant_engine_app: Engine
) -> None:
    with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
        with tenant_engine_app.begin() as conn:
            conn.execute(text("DELETE FROM punch WHERE id = :id"), {"id": punch_id})
    message = str(exc_info.value).lower()
    assert "permission denied" in message or "append-only" in message


def test_punch_trigger_blocks_update_even_when_granted(
    tenant_engine_admin: Engine, tenant_engine_app: Engine, punch_id: str
) -> None:
    with tenant_engine_admin.begin() as conn:
        conn.execute(text(f"GRANT UPDATE ON punch TO {APP_ROLE}"))
    try:
        with pytest.raises((DBAPIError, ProgrammingError)) as exc_info:
            with tenant_engine_app.begin() as conn:
                conn.execute(
                    text("UPDATE punch SET status = 'tampered' WHERE id = :id"),
                    {"id": punch_id},
                )
        assert "append-only" in str(exc_info.value).lower()
    finally:
        with tenant_engine_admin.begin() as conn:
            conn.execute(text(f"REVOKE UPDATE ON punch FROM {APP_ROLE}"))


# ---------------------------------------------------------------------------
# Constraint coverage
# ---------------------------------------------------------------------------


def test_latitude_out_of_range_rejected(punch_id: str, tenant_engine_app: Engine) -> None:
    with pytest.raises((DBAPIError, ProgrammingError)):
        with tenant_engine_app.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO punch_location "
                    "(id, punch_id, latitude, longitude, captured_at) "
                    "VALUES (:id, :pid, 91.0, 18.424100, now())"
                ),
                {"id": str(uuid.uuid4()), "pid": punch_id},
            )


def test_one_location_per_punch(punch_id: str, tenant_engine_app: Engine) -> None:
    """The unique constraint is what proves the backfill did not duplicate.

    Builds its own row rather than using the location_id fixture, because it
    needs to insert a second one and assert on the failure.
    """
    loc_id = _insert_location(tenant_engine_app, punch_id)
    try:
        with pytest.raises((DBAPIError, ProgrammingError)):
            with tenant_engine_app.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO punch_location "
                        "(id, punch_id, latitude, longitude, captured_at) "
                        "VALUES (:id, :pid, -33.924900, 18.424100, now())"
                    ),
                    {"id": str(uuid.uuid4()), "pid": punch_id},
                )
    finally:
        _delete_location(tenant_engine_app, loc_id)

# END OF FILE