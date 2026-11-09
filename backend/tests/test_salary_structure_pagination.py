"""M3.5 item 3 — cursor pagination for list_current_structures_paginated.

Tests the service function directly (Stage B style). Cursor is opaque
base64url; page boundaries are verified by walking multiple pages until
next_cursor is None and comparing the union of ids to the full set.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.core.errors import AppError
from app.db.tenant.models.people import User
from app.services.salary_structure_service import (
    create_structure,
    list_current_structures,
    list_current_structures_paginated,
)


def _mk_user(db) -> User:
    return db.query(User).filter(User.username == "admin").one()


def _mk_structure(db, user, name: str):
    return create_structure(
        db, user,
        name=name, description=None,
        pay_basis="monthly", base_rate=Decimal("10000"),
        components=[],
    )


def _seed(db, user, n: int) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for i in range(n):
        s = _mk_structure(db, user, f"S{i:02d}")
        ids.append(s.id)
    return ids


def test_paginated_first_page(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    _seed(db, user, 5)

    items, next_cursor = list_current_structures_paginated(db, limit=2)
    assert len(items) == 2
    assert next_cursor is not None


def test_paginated_walks_all_pages(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    seeded_ids = set(_seed(db, user, 5))

    seen: list[uuid.UUID] = []
    cursor: str | None = None
    pages = 0
    while True:
        items, next_cursor = list_current_structures_paginated(
            db, limit=2, cursor=cursor,
        )
        pages += 1
        seen.extend(s.id for s in items)
        if next_cursor is None:
            break
        cursor = next_cursor
        assert pages < 10, "pagination did not terminate"

    assert set(seen) == seeded_ids
    assert len(seen) == len(seeded_ids)  # no duplicates
    assert pages == 3  # 5 items / 2 per page


def test_paginated_default_limit_returns_everything_when_small(_leave_session_shared):
    db = _leave_session_shared
    user = _mk_user(db)
    _seed(db, user, 3)

    items, next_cursor = list_current_structures_paginated(db)
    # Default limit is 100, well above 3; all rows on one page.
    assert len(items) == 3
    assert next_cursor is None


def test_paginated_empty(_leave_session_shared):
    db = _leave_session_shared
    items, next_cursor = list_current_structures_paginated(db, limit=10)
    assert items == []
    assert next_cursor is None


def test_paginated_invalid_cursor_raises(_leave_session_shared):
    db = _leave_session_shared
    with pytest.raises(AppError) as exc:
        list_current_structures_paginated(db, limit=10, cursor="not-a-real-cursor")
    assert exc.value.code == "invalid_cursor"
    assert exc.value.status_code == 400


def test_unpaginated_function_still_works(_leave_session_shared):
    """Regression: Stage B callers of list_current_structures must still work."""
    db = _leave_session_shared
    user = _mk_user(db)
    _seed(db, user, 3)
    rows = list_current_structures(db)
    assert len(rows) == 3

# END OF FILE