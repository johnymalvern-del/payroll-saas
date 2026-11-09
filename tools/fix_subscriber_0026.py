"""Bring subscriber.tenant_schema_version forward from ten_0025 to ten_0026."""
import os
os.environ.setdefault("PGPASSWORD", "payroll_test_dev_password")
from sqlalchemy import create_engine, text

CONTROL_URL = (
    "postgresql+psycopg://payroll_test:payroll_test_dev_password"
    "@localhost:5432/payroll_control"
)
SLUG = "tenant-demo"
TARGET = "ten_0026"

eng = create_engine(CONTROL_URL, isolation_level="AUTOCOMMIT")
with eng.connect() as c:
    cur = c.execute(
        text("SELECT tenant_schema_version FROM subscriber WHERE slug = :s"),
        {"s": SLUG},
    ).scalar()
    print(f"current: {cur!r}")

    if cur == TARGET:
        print("already at target — no-op")
    elif cur is None:
        print("FATAL: subscriber row not found")
    else:
        r = c.execute(
            text(
                "UPDATE subscriber "
                "SET tenant_schema_version = :new, updated_at = NOW() "
                "WHERE slug = :slug AND tenant_schema_version = :old"
            ),
            {"new": TARGET, "slug": SLUG, "old": cur},
        )
        print(f"rows updated: {r.rowcount}")

    ver = c.execute(
        text("SELECT tenant_schema_version FROM subscriber WHERE slug = :s"),
        {"s": SLUG},
    ).scalar()
    print(f"after: {ver!r}")
    print(f"target reached: {ver == TARGET}")
eng.dispose()