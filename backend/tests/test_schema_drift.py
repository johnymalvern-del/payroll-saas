from sqlalchemy import text


CONTROL_TABLES = {
    'subscriber',
    'platform_user',
    'country_profile',
    'public_holiday',
    'statutory_table',
    'control_audit_log',
}


def _db_columns(engine, table_name):
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                'SELECT column_name FROM information_schema.columns '
                'WHERE table_schema = current_schema() AND table_name = :t'
            ),
            {'t': table_name},
        ).all()
    return {r[0] for r in rows}


def test_no_drift_between_models_and_db(tenant_engine_app):
    from app.db.base import Base
    import app.db.tenant.models  # noqa: F401
    import app.db.tenant.models.attendance  # noqa: F401
    import app.db.tenant.models.devices  # noqa: F401

    drift = []
    for name, table in Base.metadata.tables.items():
        if name in CONTROL_TABLES:
            continue
        expected = {c.name for c in table.columns}
        actual = _db_columns(tenant_engine_app, name)
        if not actual:
            drift.append(name + ' (no table in DB)')
        elif expected != actual:
            drift.append(
                name + ' expected_only=' + str(sorted(expected - actual))
                + ' db_only=' + str(sorted(actual - expected))
            )
    assert not drift, 'schema drift: ' + '; '.join(drift)

# END OF FILE
