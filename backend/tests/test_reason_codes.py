"""B-12: GET /attendance/reason-codes ordering and labels."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.reason_codes import (
    _label_for,
    _order_codes,
    list_reason_codes,
)
from app.db.tenant.models.organisation import Company


@pytest.fixture()
def session(tenant_engine_app):
    s = Session(bind=tenant_engine_app)
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def test_order_codes_default():
    assert _order_codes(
        (
            "device_down",
            "forgot_clock",
            "approved_site_work",
            "system_correction",
            "other",
        )
    ) == [
        "device_down",
        "forgot_clock",
        "approved_site_work",
        "system_correction",
        "other",
    ]


def test_order_codes_other_last():
    assert _order_codes(("other", "device_down")) == ["device_down", "other"]


def test_order_codes_custom_after_known():
    assert _order_codes(("device_down", "custom_x", "other")) == [
        "device_down",
        "custom_x",
        "other",
    ]


def test_label_known():
    assert _label_for("device_down") == "Device down"
    assert _label_for("other") == "Other"


def test_label_unknown():
    assert _label_for("custom_code") == "Custom Code"


def test_list_reason_codes_defaults_when_no_company(session):
    session.execute(text("DELETE FROM company"))
    session.flush()

    out = list_reason_codes(session, None)
    codes = [i.code for i in out.items]
    assert codes == [
        "device_down",
        "forgot_clock",
        "approved_site_work",
        "system_correction",
        "other",
    ]
    assert all(
        i.requires_note is (i.code == "other") for i in out.items
    )


def test_list_reason_codes_company_override(session):
    session.add(
        Company(
            legal_name="Test Co",
            country_code="ZA",
            currency="ZAR",
            default_timezone="Africa/Johannesburg",
            settings={"attendance": {"reason_codes": ["custom_a", "other"]}},
            row_version=1,
        )
    )
    session.flush()

    out = list_reason_codes(session, None)
    codes = [i.code for i in out.items]
    assert codes[-1] == "other"
    assert "custom_a" in codes
    custom = next(i for i in out.items if i.code == "custom_a")
    assert custom.label == "Custom A"
    assert custom.requires_note is False