
"""Demo seed.

Refuses to run unless ENVIRONMENT is development or test, or if the demo
tenant already exists. Creates one tenant with 5 users, one per role.
Never runs in production.
"""
from __future__ import annotations

import sys

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.session import tenant_session
from app.services.provisioning import _tenant_db_name, provision_tenant

configure_logging()
log = get_logger("app.scripts.seed_demo")

DEMO_SLUG = "demo"
DEMO_COMPANY = "Demo Payroll (Pty) Ltd"
USERS = [
    ("demo-admin", "DemoAdmin123!", "payroll_admin"),
    ("demo-hr", "DemoHr123!", "hr"),
    ("demo-mgr", "DemoMgr123!", "manager"),
    ("demo-emp", "DemoEmp123!", "employee"),
    ("demo-audit", "DemoAudit123!", "auditor"),
]


def main() -> int:
    settings = get_settings()
    if settings.environment not in ("development", "test"):
        log.error("seed_demo.refused", environment=settings.environment,
                  reason="not development/test")
        return 1

    with control_session() as session:
        exists = session.query(Subscriber).filter(Subscriber.slug == DEMO_SLUG).one_or_none()
        if exists is not None:
            log.error("seed_demo.already_exists", slug=DEMO_SLUG)
            print(f"Demo tenant '{DEMO_SLUG}' already exists. Delete it first if you want to reseed.")
            return 1

    admin_username, admin_password, _admin_role = USERS[0]
    result = provision_tenant(
        slug=DEMO_SLUG,
        name=DEMO_COMPANY,
        admin_username=admin_username,
        admin_password_hash=hash_password(admin_password),
    )
    db_name = _tenant_db_name(DEMO_SLUG)

    from app.db.tenant.models.people import User

    with tenant_session(db_name) as s:
        # The first admin is already created by provision_tenant. Update it to
        # must_change_password=False so we can log in immediately for demos,
        # and add the other four users.
        admin = s.query(User).filter(User.username == admin_username).one()
        admin.must_change_password = False
        for username, password, role in USERS[1:]:
            s.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                    is_active=True,
                    must_change_password=False,
                )
            )

    log.info("seed_demo.created", slug=DEMO_SLUG, db=db_name,
             subscriber_id=str(result.subscriber_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
