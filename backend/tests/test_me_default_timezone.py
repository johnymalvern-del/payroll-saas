"""B-1: /auth/me exposes Company.default_timezone (nullable)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.auth.me import UserMeOut, get_me
from app.db.tenant.models.organisation import Company


@pytest.fixture()
def session(tenant_engine_app):
    s = Session(bind=tenant_engine_app)
    try:
        yield s
    finally:
        s.rollback()
        s.close()


class _FakeUser:
    def __init__(self, role: str = "employee") -> None:
        self.id = uuid.uuid4()
        self.username = "tester"
        self.role = role
        self.employee_id = None
        self.must_change_password = False


def test_me_includes_company_default_timezone(session):
    session.add(
        Company(
            legal_name="Test Co",
            country_code="ZA",
            currency="ZAR",
            default_timezone="Europe/London",
            settings={},
            row_version=1,
        )
    )
    session.flush()

    out = get_me(session, _FakeUser())
    assert isinstance(out, UserMeOut)
    assert out.default_timezone == "Europe/London"


def test_me_missing_company_yields_null(session):
    session.execute(text("DELETE FROM company"))
    session.flush()

    out = get_me(session, _FakeUser())
    assert out.default_timezone is None