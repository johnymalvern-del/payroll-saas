"""Seed control DB with the empty South African country profile template.

Run with:  python -m app.scripts.seed

The template contains NO real legal or tax values - everything that must come
from an official source is `null` and flagged with `_verify_flag: true`.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

from app.core.logging import configure_logging, get_logger
from app.db.control.models import CountryProfile
from app.db.control.session import control_session

configure_logging()
log = get_logger("app.scripts.seed")


def _load_za_template() -> dict:
    path = (
        Path(__file__).resolve().parent.parent / "data" / "country_profiles" / "za.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    template = _load_za_template()
    with control_session() as session:
        existing = session.scalar(
            select(CountryProfile).where(
                CountryProfile.code == template["code"],
                CountryProfile.version == template["version"],
            )
        )
        if existing is not None:
            log.info("seed.za_profile_exists", version=template["version"])
            return 0
        session.add(
            CountryProfile(
                code=template["code"],
                name=template["name"],
                version=template["version"],
                effective_from=date.fromisoformat(template["effective_from"]),
                data=template["data"],
            )
        )
    log.info("seed.za_profile_created")
    return 0


if __name__ == "__main__":
    sys.exit(main())