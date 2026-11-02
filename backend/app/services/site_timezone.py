"""Shared site-timezone resolution helper (B-5/B-11).

Given a batch of employee ids, returns {employee_id: tz_string | None}.
Uses each employee's site timezone where available; falls back to
Company.default_timezone; returns None only when both are unavailable
(e.g. unprovisioned tenant).

Performs at most three queries (company, employees, sites), never
per-employee, so it is safe to call once per list request.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.tenant.models.organisation import Company, Site
from app.db.tenant.models.people import Employee


def site_timezone_map(
    db,
    employee_ids: list[uuid.UUID],
) -> dict[uuid.UUID, str | None]:
    if not employee_ids:
        return {}

    company = db.scalar(select(Company))
    default_tz: str | None = (
        company.default_timezone if company is not None else None
    )

    emp_rows = db.execute(
        select(Employee.id, Employee.site_id).where(
            Employee.id.in_(employee_ids)
        )
    ).all()
    site_ids = [r[1] for r in emp_rows if r[1] is not None]

    site_tz_by_id: dict[uuid.UUID, str] = {}
    if site_ids:
        for sid, tz in db.execute(
            select(Site.id, Site.timezone).where(Site.id.in_(site_ids))
        ).all():
            site_tz_by_id[sid] = tz

    out: dict[uuid.UUID, str | None] = {}
    for emp_id, sid in emp_rows:
        if sid is not None and sid in site_tz_by_id:
            out[emp_id] = site_tz_by_id[sid]
        else:
            out[emp_id] = default_tz
    return out