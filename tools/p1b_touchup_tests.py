"""Phase 1B touch-up — fix snapshot test, add 3 new tests + cross-tenant fixture."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "backend" / "tests" / "test_intelligence_decision_records.py"
s = P.read_text(encoding="utf-8")

# 1. Imports for concurrency
if "import threading" not in s:
    anchor = "import uuid\n"
    if anchor not in s:
        raise SystemExit("FATAL: 'import uuid' not found")
    s = s.replace(anchor, "import threading\nimport time\nimport uuid\n", 1)
    print("added threading + time imports")

# 2. Fix the vacuous assertion
old_assert = '''    # trigger raises
    assert "append-only" in str(exc_info.value).lower() or True
'''
new_assert = '''    # trigger raises with expected message
    msg = str(exc_info.value).lower()
    assert "append-only" in msg, (
        f"Expected append-only exception, got: {exc_info.value!r}"
    )
    svc_db.rollback()
'''
if old_assert not in s:
    raise SystemExit("FATAL: 'assert append-only ... or True' block not matched")
s = s.replace(old_assert, new_assert, 1)
print("fixed test_snapshot_update_raises assertion")

# 3. Append new tests + two_tenants fixture
s = s.rstrip() + '''


# ============================================================
# Phase 1B touch-up additions
# ============================================================


def test_policy_and_statutory_version_round_trip(svc_db):
    """Both versions stored and returned unchanged."""
    emp = _mk_emp(svc_db)
    user = _mk_user(svc_db)
    d = create_decision_record(
        svc_db, user,
        workflow="leave_decision", employee_id=emp.id,
        source_type="leave_request",
        evidence_payload={"x": 1},
        policy_version="2026.11-v1",
        statutory_version="ZA-2026-2027",
    )
    svc_db.commit()
    svc_db.refresh(d)
    assert d.policy_version == "2026.11-v1"
    assert d.statutory_version == "ZA-2026-2027"


@pytest.fixture()
def two_tenants():
    """Provision two independent tenants for cross-tenant isolation tests."""
    from app.core.security import hash_password as _hp
    from app.services.provisioning import (
        provision_tenant as _prov,
        _drop_tenant_database as _drop,
        _tenant_db_name as _name,
    )
    from app.db.control.models import Subscriber as _Sub
    from app.db.control.session import control_session as _cs

    slug_a = f"xta-{uuid.uuid4().hex[:8]}"
    slug_b = f"xtb-{uuid.uuid4().hex[:8]}"
    res_a = _prov(slug=slug_a, name="X-A", admin_username="admin",
                  admin_password_hash=_hp("X-A-test-123!"))
    res_b = _prov(slug=slug_b, name="X-B", admin_username="admin",
                  admin_password_hash=_hp("X-B-test-123!"))
    try:
        yield res_a, res_b
    finally:
        for slug in (slug_a, slug_b):
            try:
                _drop(_name(slug))
            except Exception:
                pass
            with _cs() as sess:
                row = sess.query(_Sub).filter(_Sub.slug == slug).one_or_none()
                if row is not None:
                    sess.delete(row)


def test_cross_tenant_isolation(two_tenants):
    """Tenant A's decision + snapshot are invisible to Tenant B."""
    res_a, res_b = two_tenants

    eng_a = get_tenant_engine(res_a.tenant_db_name)
    eng_b = get_tenant_engine(res_b.tenant_db_name)
    s_a = Session(eng_a)
    s_b = Session(eng_b)
    try:
        user_a = _admin(s_a)
        emp_a = _mk_emp(s_a)
        s_a.commit()

        d = create_decision_record(
            s_a, user_a,
            workflow="leave_decision", employee_id=emp_a.id,
            source_type="leave_request",
            evidence_payload={"note": "only-in-A"},
        )
        s_a.commit()
        decision_id = d.id
        snapshot_id = d.evidence_snapshot_id
        assert decision_id is not None
        assert snapshot_id is not None

        # Tenant B cannot read the record
        found_b = s_b.scalar(
            select(IntelligenceDecision).where(
                IntelligenceDecision.id == decision_id
            )
        )
        assert found_b is None, "Tenant B sees Tenant A's decision"

        # Tenant B cannot read the snapshot
        snap_b = s_b.get(IntelligenceEvidenceSnapshot, snapshot_id)
        assert snap_b is None, "Tenant B sees Tenant A's snapshot"

        # Tenant B cannot modify the record
        result = s_b.execute(
            text(
                "UPDATE intelligence_decision SET explanation = 'tampered' "
                "WHERE id = :id"
            ),
            {"id": str(decision_id)},
        )
        assert result.rowcount == 0, "Tenant B modified Tenant A's row"
        s_b.commit()

        # Verify Tenant A's record is unchanged
        s_a.expire_all()
        d_check = s_a.get(IntelligenceDecision, decision_id)
        assert d_check is not None
        assert d_check.explanation is None

    finally:
        s_a.close()
        s_b.close()
        eng_a.dispose()
        eng_b.dispose()


def test_concurrent_idempotency(api_tenant):
    """Two concurrent transactions, same key + same payload -> 1 record."""
    from sqlalchemy import func as _func
    from sqlalchemy import create_engine as _ce
    from app.db.tenant.models.people import User as _User

    # Setup: employee + user committed so both threads can see them
    eng_main = get_tenant_engine(api_tenant.tenant_db_name)
    s_main = Session(eng_main)
    try:
        user = _admin(s_main)
        emp = _mk_emp(s_main)
        s_main.commit()
        user_id = user.id
        emp_id = emp.id
    finally:
        s_main.close()
        eng_main.dispose()

    tenant_url = (
        f"postgresql+psycopg://payroll_test:payroll_test_dev_password"
        f"@localhost:5432/{api_tenant.tenant_db_name}"
    )

    barrier = threading.Barrier(2, timeout=10)
    results: list[str] = []
    errors: list[str] = []

    def worker():
        engine = _ce(tenant_url, future=True)
        s = Session(engine)
        try:
            u = s.get(_User, user_id)
            assert u is not None
            barrier.wait()
            time.sleep(0.03)  # widen race window so both pass pre-check
            d = create_decision_record(
                s, u,
                workflow="leave_decision",
                employee_id=emp_id,
                source_type="leave_request",
                evidence_payload={"x": 1},
                idempotency_key="race-key-touchup-001",
            )
            s.commit()
            results.append(str(d.id))
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")
            try:
                s.rollback()
            except Exception:
                pass
        finally:
            s.close()
            engine.dispose()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    # Exactly one record
    eng_check = get_tenant_engine(api_tenant.tenant_db_name)
    s_check = Session(eng_check)
    try:
        count = s_check.scalar(
            select(_func.count()).select_from(IntelligenceDecision).where(
                IntelligenceDecision.idempotency_key == "race-key-touchup-001"
            )
        )
        assert count == 1, (
            f"expected exactly 1 record, got {count}; "
            f"results={results} errors={errors}"
        )

        # Exactly one snapshot for that decision
        row = s_check.scalar(
            select(IntelligenceDecision).where(
                IntelligenceDecision.idempotency_key == "race-key-touchup-001"
            )
        )
        assert row is not None
        snap_count = s_check.scalar(
            select(_func.count()).select_from(IntelligenceEvidenceSnapshot)
            .where(IntelligenceEvidenceSnapshot.decision_id == row.id)
        )
        assert snap_count == 1
    finally:
        s_check.close()
        eng_check.dispose()

    # Both workers succeeded with the same decision id
    assert len(errors) == 0, f"unexpected worker errors: {errors}"
    assert len(results) == 2, f"both workers should succeed, got {results}"
    assert results[0] == results[1], f"workers returned different ids: {results}"
'''
P.write_text(s, encoding="utf-8")
print("appended 3 new tests + cross-tenant fixture; fixed snapshot_update test")