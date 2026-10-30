"""Statutory loader tests (Chapter 4, Bundle 001)."""
from __future__ import annotations

import json
import pathlib
import uuid
from datetime import date

import pytest
import sqlalchemy as sa

from app.db.control.session import control_session
from app.services import statutory_loader as sl


FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "fake_tax_tables.json"


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    with control_session() as s:
        sl.bootstrap_schema(s.get_bind())
    yield


@pytest.fixture()
def fake_tables() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


@pytest.fixture()
def unique_version() -> str:
    return f"test_{uuid.uuid4().hex[:10]}"


@pytest.fixture()
def loaded_versions():
    created: list[tuple[str, str, str]] = []
    yield created
    if not created:
        return
    with control_session() as s:
        eng = s.get_bind()
        with eng.begin() as conn:
            for cc, tt, v in created:
                row = conn.execute(sa.text(
                    "SELECT id FROM statutory_table WHERE country_code=:cc AND table_type=:tt AND version=:v"
                ), {"cc": cc, "tt": tt, "v": v}).first()
                if row is None:
                    continue
                tid = row[0]
                conn.execute(sa.text("DELETE FROM statutory_table_row WHERE statutory_table_id=:id"), {"id": tid})
                conn.execute(sa.text("DELETE FROM statutory_table_load_log WHERE statutory_table_id=:id"), {"id": tid})
                conn.execute(sa.text("DELETE FROM statutory_table WHERE id=:id"), {"id": tid})


def _rebrand(doc: dict, *, version: str, **overrides) -> dict:
    out = {k: v for k, v in doc.items() if not k.startswith("_")}
    out["version"] = version
    out.update(overrides)
    return out


def test_validate_rejects_overlap_after_apply(fake_tables, unique_version, loaded_versions):
    with control_session() as s:
        eng = s.get_bind()
    doc1 = _rebrand(fake_tables["tables"][0], version=unique_version)
    sl.apply_document(eng, doc1, actor_user_id=None, typed_version=unique_version)
    loaded_versions.append((doc1["country_code"], doc1["table_type"], unique_version))

    v2 = unique_version + "b"
    doc2 = _rebrand(fake_tables["tables"][0], version=v2)
    with pytest.raises(ValueError, match="overlaps"):
        sl.apply_document(eng, doc2, actor_user_id=None, typed_version=v2)


def test_validate_rejects_brackets_with_gap(fake_tables, unique_version):
    doc = _rebrand(fake_tables["tables"][0], version=unique_version)
    doc["rows"][1]["lower_bound"] = "1500"
    res = sl.validate_document(doc)
    assert not res.ok
    assert any("contiguous" in e for e in res.errors)


def test_validate_rejects_rate_out_of_range(fake_tables, unique_version):
    doc = _rebrand(fake_tables["tables"][0], version=unique_version)
    doc["rows"][0]["rate"] = "1.5"
    res = sl.validate_document(doc)
    assert not res.ok
    assert any("[0, 1]" in e or ("rate" in e and "range" in e) for e in res.errors)


def test_validate_rejects_missing_source_url(fake_tables, unique_version):
    doc = _rebrand(fake_tables["tables"][0], version=unique_version)
    doc["source_url"] = None
    res = sl.validate_document(doc)
    assert not res.ok
    assert any("source_url" in e for e in res.errors)


def test_validate_rejects_http_source_url(fake_tables, unique_version):
    doc = _rebrand(fake_tables["tables"][0], version=unique_version)
    doc["source_url"] = "http://example.invalid/x"
    res = sl.validate_document(doc)
    assert not res.ok
    assert any("https://" in e for e in res.errors)


def test_validate_rejects_missing_required_row_keys(fake_tables, unique_version):
    doc = next(t for t in fake_tables["tables"] if t["table_type"] == "uif")
    doc = _rebrand(doc, version=unique_version)
    doc["rows"] = [r for r in doc["rows"] if r["row_key"] != "monthly_ceiling"]
    res = sl.validate_document(doc)
    assert not res.ok
    assert any("monthly_ceiling" in e for e in res.errors)


def test_validate_accepts_all_fake_tables(fake_tables):
    for t in fake_tables["tables"]:
        res = sl.validate_document(t)
        assert res.ok, f"{t['table_type']}: {res.errors}"


def test_confirm_writes_when_typed_version_matches(fake_tables, unique_version, loaded_versions):
    with control_session() as s:
        eng = s.get_bind()
    doc = _rebrand(fake_tables["tables"][0], version=unique_version)
    result = sl.apply_document(eng, doc, actor_user_id=None, typed_version=unique_version)
    loaded_versions.append((doc["country_code"], doc["table_type"], unique_version))
    assert result["table_id"]

    with control_session() as s:
        n = s.execute(sa.text(
            "SELECT COUNT(*) FROM statutory_table WHERE version=:v"
        ), {"v": unique_version}).scalar()
        assert n == 1


def test_confirm_refuses_when_typed_version_differs(fake_tables, unique_version):
    with control_session() as s:
        eng = s.get_bind()
    doc = _rebrand(fake_tables["tables"][0], version=unique_version)
    with pytest.raises(ValueError, match="typed confirmation mismatch"):
        sl.apply_document(eng, doc, actor_user_id=None, typed_version="WRONG")


def test_effective_dating_selects_correct_row(fake_tables, unique_version, loaded_versions):
    with control_session() as s:
        eng = s.get_bind()

    doc1 = _rebrand(fake_tables["tables"][0], version=unique_version + "_a",
                    effective_from="2025-01-01", effective_to="2025-12-31")
    doc2 = _rebrand(fake_tables["tables"][0], version=unique_version + "_b",
                    effective_from="2026-01-01", effective_to="2026-12-31")
    sl.apply_document(eng, doc1, actor_user_id=None, typed_version=doc1["version"])
    sl.apply_document(eng, doc2, actor_user_id=None, typed_version=doc2["version"])
    loaded_versions.extend([
        (doc1["country_code"], doc1["table_type"], doc1["version"]),
        (doc2["country_code"], doc2["table_type"], doc2["version"]),
    ])

    got = sl.get_active_table(eng, "ZA", "tax_bracket", date(2025, 6, 1))
    assert got is not None and got["version"] == doc1["version"]

    got2 = sl.get_active_table(eng, "ZA", "tax_bracket", date(2026, 6, 1))
    assert got2 is not None and got2["version"] == doc2["version"]

    missing = sl.get_active_table(eng, "ZA", "tax_bracket", date(2030, 1, 1))
    assert missing is None


def test_end_date_shortens_window(fake_tables, unique_version, loaded_versions):
    with control_session() as s:
        eng = s.get_bind()
    doc = _rebrand(fake_tables["tables"][0], version=unique_version,
                   effective_from="2025-01-01", effective_to="2030-12-31")
    result = sl.apply_document(eng, doc, actor_user_id=None, typed_version=unique_version)
    loaded_versions.append((doc["country_code"], doc["table_type"], unique_version))
    tid = result["table_id"]

    sl.end_date(eng, tid, new_end_date="2025-12-31", actor_user_id=None)

    with control_session() as s:
        et = s.execute(sa.text(
            "SELECT effective_to FROM statutory_table WHERE id=:id"
        ), {"id": tid}).scalar()
        assert et == date(2025, 12, 31)


def test_end_date_refuses_before_effective_from(fake_tables, unique_version, loaded_versions):
    with control_session() as s:
        eng = s.get_bind()
    doc = _rebrand(fake_tables["tables"][0], version=unique_version,
                   effective_from="2025-06-01", effective_to="2025-12-31")
    result = sl.apply_document(eng, doc, actor_user_id=None, typed_version=unique_version)
    loaded_versions.append((doc["country_code"], doc["table_type"], unique_version))
    with pytest.raises(ValueError, match="< effective_from"):
        sl.end_date(eng, result["table_id"], new_end_date="2025-05-31", actor_user_id=None)


def test_diff_reports_new_rows(fake_tables, unique_version, loaded_versions):
    with control_session() as s:
        eng = s.get_bind()
    doc1 = _rebrand(fake_tables["tables"][0], version=unique_version + "_base")
    sl.apply_document(eng, doc1, actor_user_id=None, typed_version=doc1["version"])
    loaded_versions.append((doc1["country_code"], doc1["table_type"], doc1["version"]))

    current = sl._fetch_current_active(eng, "ZA", "tax_bracket")
    doc2 = _rebrand(fake_tables["tables"][0], version=unique_version + "_next",
                    effective_from="2031-01-01", effective_to="2031-12-31")
    diff = sl.compute_diff(doc2, current)
    assert diff.action == "replaces"
    assert diff.replaced_version == unique_version + "_base"

# END OF FILE
