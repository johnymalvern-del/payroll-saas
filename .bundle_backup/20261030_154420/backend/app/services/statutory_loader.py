"""Statutory table loader for the control DB (F1: PowerShell-invoked, no HTTP)."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine


VALID_TABLE_TYPES = {
    "tax_bracket", "tax_rebate", "tax_threshold", "medical_credit",
    "retirement_limit", "uif", "sdl",
}

REQUIRED_ROW_KEYS = {
    "tax_rebate": {"primary", "secondary_65", "tertiary_75"},
    "tax_threshold": {"below_age_65", "age_65_to_74", "age_75_plus"},
    "medical_credit": {"first_member", "additional_member", "first_dependant"},
    "uif": {"employee_rate", "employer_rate", "monthly_ceiling"},
    "sdl": {"rate", "exemption_threshold_annual"},
    "retirement_limit": {"percentage_of_taxable_income", "annual_cap"},
}

REQUIRED_COLUMNS = {
    "id": "UUID",
    "country_code": "VARCHAR(2)",
    "table_type": "VARCHAR(40)",
    "version": "VARCHAR(40)",
    "tax_year": "VARCHAR(20)",
    "source_document": "VARCHAR(200)",
    "source_url": "VARCHAR(500)",
    "source_date": "DATE",
    "effective_from": "DATE",
    "effective_to": "DATE",
    "is_active": "BOOLEAN DEFAULT TRUE",
    "loaded_by_user_id": "UUID",
    "loaded_at": "TIMESTAMPTZ DEFAULT NOW()",
    "row_version": "INTEGER DEFAULT 1",
}


def _is_int_like(data_type: str) -> bool:
    t = (data_type or "").lower()
    return any(x in t for x in ("int", "numeric", "decimal"))


def bootstrap_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        tables = {r[0] for r in conn.execute(sa.text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        ))}

        if "statutory_table" in tables:
            existing_cols = {row[0]: (row[1] or "").lower() for row in conn.execute(sa.text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='statutory_table'"
            ))}

            # Legacy 0001 shape has `version INTEGER`; our shape needs VARCHAR(40).
            if _is_int_like(existing_cols.get("version", "")):
                n_main = conn.scalar(sa.text("SELECT COUNT(*) FROM statutory_table")) or 0
                n_row = 0
                n_log = 0
                if "statutory_table_row" in tables:
                    n_row = conn.scalar(sa.text("SELECT COUNT(*) FROM statutory_table_row")) or 0
                if "statutory_table_load_log" in tables:
                    n_log = conn.scalar(sa.text("SELECT COUNT(*) FROM statutory_table_load_log")) or 0
                if (n_main + n_row + n_log) > 0:
                    raise RuntimeError(
                        f"statutory_table has legacy INTEGER version column with data "
                        f"(main={n_main}, row={n_row}, log={n_log}). "
                        "Manual migration required: ALTER COLUMN version TYPE VARCHAR(40) "
                        "USING version::text; then rerun bootstrap_schema."
                    )
                conn.execute(sa.text("DROP TABLE statutory_table CASCADE"))
                conn.execute(sa.text("DROP TABLE IF EXISTS statutory_table_row CASCADE"))
                conn.execute(sa.text("DROP TABLE IF EXISTS statutory_table_load_log CASCADE"))
                tables.discard("statutory_table")

            else:
                # Table exists with our shape (or near enough) — add missing columns only
                for col, typ in REQUIRED_COLUMNS.items():
                    if col not in existing_cols:
                        conn.execute(sa.text(
                            f"ALTER TABLE statutory_table ADD COLUMN {col} {typ}"
                        ))

        if "statutory_table" not in tables:
            conn.execute(sa.text("""
                CREATE TABLE statutory_table (
                    id UUID PRIMARY KEY,
                    country_code VARCHAR(2) NOT NULL,
                    table_type VARCHAR(40) NOT NULL,
                    version VARCHAR(40) NOT NULL,
                    tax_year VARCHAR(20),
                    source_document VARCHAR(200) NOT NULL,
                    source_url VARCHAR(500) NOT NULL,
                    source_date DATE NOT NULL,
                    effective_from DATE NOT NULL,
                    effective_to DATE NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    loaded_by_user_id UUID,
                    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    row_version INTEGER NOT NULL DEFAULT 1,
                    UNIQUE (country_code, table_type, version)
                )
            """))

        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS statutory_table_row (
                id UUID PRIMARY KEY,
                statutory_table_id UUID NOT NULL REFERENCES statutory_table(id) ON DELETE CASCADE,
                row_key VARCHAR(40) NOT NULL,
                row_data JSONB NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                UNIQUE (statutory_table_id, row_key)
            )
        """))

        conn.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS statutory_table_load_log (
                id UUID PRIMARY KEY,
                action VARCHAR(20) NOT NULL,
                statutory_table_id UUID,
                actor_user_id UUID,
                payload JSONB NOT NULL,
                diff_summary JSONB,
                typed_confirmation_matched BOOLEAN NOT NULL DEFAULT FALSE,
                occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))

        conn.execute(sa.text(
            "CREATE INDEX IF NOT EXISTS ix_statutory_table_active "
            "ON statutory_table (country_code, table_type, effective_from, effective_to) "
            "WHERE is_active"
        ))


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _parse_date(value: Any, name: str, errors: list[str]) -> date | None:
    if value is None:
        errors.append(f"{name} is required")
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        errors.append(f"{name} not a valid ISO date: {value!r}")
        return None


def _parse_decimal(value: Any, name: str, errors: list[str]) -> Decimal | None:
    if value is None:
        errors.append(f"{name} is required")
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        errors.append(f"{name} not a valid decimal: {value!r}")
        return None


def validate_document(doc: dict) -> ValidationResult:
    errors: list[str] = []

    for name in ("country_code", "table_type", "version", "source_document",
                 "source_url", "source_date", "effective_from", "effective_to"):
        if not doc.get(name):
            errors.append(f"{name} is required")

    cc = doc.get("country_code")
    if cc and (not isinstance(cc, str) or len(cc) != 2 or not cc.isalpha() or not cc.isupper()):
        errors.append(f"country_code must be 2 uppercase letters: {cc!r}")

    tt = doc.get("table_type")
    if tt and tt not in VALID_TABLE_TYPES:
        errors.append(f"table_type must be one of {sorted(VALID_TABLE_TYPES)}: {tt!r}")

    su = doc.get("source_url")
    if su and not (isinstance(su, str) and su.startswith("https://")):
        errors.append(f"source_url must start with https://: {su!r}")

    ef = _parse_date(doc.get("effective_from"), "effective_from", errors)
    et = _parse_date(doc.get("effective_to"), "effective_to", errors)
    _parse_date(doc.get("source_date"), "source_date", errors)
    if ef and et and et < ef:
        errors.append("effective_to must be >= effective_from")

    rows = doc.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("rows must be a non-empty list")
        return ValidationResult(errors=errors)

    if tt == "tax_bracket":
        _validate_tax_brackets(rows, errors)
    elif tt in REQUIRED_ROW_KEYS:
        present = {r.get("row_key") for r in rows if isinstance(r, dict)}
        missing = REQUIRED_ROW_KEYS[tt] - present
        extra = present - REQUIRED_ROW_KEYS[tt]
        if missing:
            errors.append(f"missing required row_keys for {tt}: {sorted(missing)}")
        if extra:
            errors.append(f"unexpected row_keys for {tt}: {sorted(extra)}")

    return ValidationResult(errors=errors)


def _validate_tax_brackets(rows: list, errors: list[str]) -> None:
    parsed: list[tuple[Decimal, Decimal | None]] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"bracket row {i} not an object")
            continue
        try:
            lb = Decimal(str(row.get("lower_bound")))
            ub = None if row.get("upper_bound") is None else Decimal(str(row["upper_bound"]))
            rate = Decimal(str(row.get("rate")))
        except (InvalidOperation, TypeError, ValueError):
            errors.append(f"bracket {i}: numeric parse failed")
            continue
        _parse_decimal(row.get("base_tax"), f"bracket {i} base_tax", errors)
        if not (Decimal(0) <= rate <= Decimal(1)):
            errors.append(f"bracket {i}: rate {rate} not in [0, 1]")
        parsed.append((lb, ub))

    if parsed and parsed[0][0] != Decimal(0):
        errors.append(f"first bracket lower_bound must be 0, got {parsed[0][0]}")
    for i in range(len(parsed) - 1):
        if parsed[i][1] != parsed[i + 1][0]:
            errors.append(
                f"brackets not contiguous: [{i}] ends at {parsed[i][1]}, "
                f"[{i+1}] starts at {parsed[i+1][0]}"
            )
    if parsed and parsed[-1][1] is not None:
        errors.append("last bracket upper_bound must be null")


@dataclass
class DiffSummary:
    action: str
    replaced_version: str | None
    rows_added: int
    rows_removed: int
    rows_changed: int

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "replaced_version": self.replaced_version,
            "rows_added": self.rows_added,
            "rows_removed": self.rows_removed,
            "rows_changed": self.rows_changed,
        }


def _row_key_map(rows: list) -> dict:
    return {r.get("row_key"): r for r in rows if isinstance(r, dict)}


def compute_diff(new_doc: dict, current: dict | None) -> DiffSummary:
    if current is None:
        return DiffSummary("new", None, len(new_doc.get("rows", [])), 0, 0)
    old_map = _row_key_map(current.get("rows", []))
    new_map = _row_key_map(new_doc.get("rows", []))
    added = set(new_map) - set(old_map)
    removed = set(old_map) - set(new_map)
    common = set(old_map) & set(new_map)
    changed = {k for k in common if old_map[k] != new_map[k]}
    return DiffSummary("replaces", current.get("version"), len(added), len(removed), len(changed))


def _fetch_current_active(engine: Engine, country_code: str, table_type: str) -> dict | None:
    with engine.connect() as conn:
        head = conn.execute(sa.text(
            "SELECT id, version FROM statutory_table "
            "WHERE country_code=:cc AND table_type=:tt AND is_active "
            "ORDER BY effective_from DESC LIMIT 1"
        ), {"cc": country_code, "tt": table_type}).first()
        if head is None:
            return None
        rows = conn.execute(sa.text(
            "SELECT row_key, row_data, sort_order FROM statutory_table_row "
            "WHERE statutory_table_id=:tid ORDER BY sort_order"
        ), {"tid": head[0]}).all()
        return {
            "id": str(head[0]),
            "version": head[1],
            "rows": [{"row_key": r[0], **r[1], "sort_order": r[2]} for r in rows],
        }


def apply_document(engine: Engine, doc: dict, *, actor_user_id: str | None, typed_version: str) -> dict:
    res = validate_document(doc)
    if not res.ok:
        raise ValueError("validation failed: " + "; ".join(res.errors))
    if typed_version != doc["version"]:
        raise ValueError(
            f"typed confirmation mismatch: expected {doc['version']!r}, got {typed_version!r}"
        )

    current = _fetch_current_active(engine, doc["country_code"], doc["table_type"])
    diff = compute_diff(doc, current)
    table_id = uuid.uuid4()

    with engine.begin() as conn:
        overlap = conn.execute(sa.text(
            "SELECT version FROM statutory_table "
            "WHERE country_code=:cc AND table_type=:tt AND is_active "
            "AND effective_from <= :et AND effective_to >= :ef"
        ), {
            "cc": doc["country_code"], "tt": doc["table_type"],
            "ef": doc["effective_from"], "et": doc["effective_to"],
        }).first()
        if overlap is not None:
            raise ValueError(
                f"overlaps active version {overlap[0]!r}; end-date that version first"
            )

        conn.execute(sa.text(
            "INSERT INTO statutory_table "
            "(id, country_code, table_type, version, tax_year, source_document, source_url, "
            " source_date, effective_from, effective_to, is_active, loaded_by_user_id) "
            "VALUES (:id, :cc, :tt, :v, :ty, :sd, :su, :sdate, :ef, :et, TRUE, :uid)"
        ), {
            "id": table_id, "cc": doc["country_code"], "tt": doc["table_type"],
            "v": doc["version"], "ty": doc.get("tax_year"),
            "sd": doc["source_document"], "su": doc["source_url"],
            "sdate": doc["source_date"], "ef": doc["effective_from"], "et": doc["effective_to"],
            "uid": actor_user_id,
        })

        for i, row in enumerate(doc["rows"]):
            row_data = {k: v for k, v in row.items() if k not in ("row_key", "sort_order")}
            conn.execute(sa.text(
                "INSERT INTO statutory_table_row "
                "(id, statutory_table_id, row_key, row_data, sort_order) "
                "VALUES (:id, :tid, :rk, CAST(:rd AS JSONB), :so)"
            ), {
                "id": uuid.uuid4(), "tid": table_id, "rk": row["row_key"],
                "rd": json.dumps(row_data, default=str), "so": row.get("sort_order", i),
            })

        conn.execute(sa.text(
            "INSERT INTO statutory_table_load_log "
            "(id, action, statutory_table_id, actor_user_id, payload, diff_summary, "
            " typed_confirmation_matched) "
            "VALUES (:id, 'confirm', :tid, :uid, CAST(:p AS JSONB), CAST(:d AS JSONB), TRUE)"
        ), {
            "id": uuid.uuid4(), "tid": table_id, "uid": actor_user_id,
            "p": json.dumps(doc, default=str),
            "d": json.dumps(diff.to_dict()),
        })

    return {"table_id": str(table_id), "diff": diff.to_dict()}


def end_date(engine: Engine, table_id: str, *, new_end_date: str, actor_user_id: str | None) -> dict:
    with engine.begin() as conn:
        row = conn.execute(sa.text(
            "SELECT effective_from, version FROM statutory_table WHERE id=:id"
        ), {"id": table_id}).first()
        if row is None:
            raise ValueError(f"table {table_id} not found")
        ef, version = row
        et_new = date.fromisoformat(new_end_date)
        if et_new < ef:
            raise ValueError(f"new end-date {et_new} < effective_from {ef}")
        conn.execute(sa.text(
            "UPDATE statutory_table SET effective_to=:et, row_version=row_version+1 WHERE id=:id"
        ), {"et": et_new, "id": table_id})
        conn.execute(sa.text(
            "INSERT INTO statutory_table_load_log "
            "(id, action, statutory_table_id, actor_user_id, payload, typed_confirmation_matched) "
            "VALUES (:id, 'end_date', :tid, :uid, CAST(:p AS JSONB), TRUE)"
        ), {
            "id": uuid.uuid4(), "tid": table_id, "uid": actor_user_id,
            "p": json.dumps({"new_end_date": new_end_date, "version": version}),
        })
    return {"table_id": table_id, "new_end_date": new_end_date}


def get_active_table(engine: Engine, country_code: str, table_type: str, on_date: date) -> dict | None:
    with engine.connect() as conn:
        head = conn.execute(sa.text(
            "SELECT id, version, effective_from, effective_to FROM statutory_table "
            "WHERE country_code=:cc AND table_type=:tt AND is_active "
            "AND effective_from <= :d AND effective_to >= :d "
            "ORDER BY effective_from DESC LIMIT 1"
        ), {"cc": country_code, "tt": table_type, "d": on_date}).first()
        if head is None:
            return None
        rows = conn.execute(sa.text(
            "SELECT row_key, row_data, sort_order FROM statutory_table_row "
            "WHERE statutory_table_id=:tid ORDER BY sort_order"
        ), {"tid": head[0]}).all()
        return {
            "id": str(head[0]), "version": head[1],
            "effective_from": head[2].isoformat(), "effective_to": head[3].isoformat(),
            "rows": [{"row_key": r[0], **r[1], "sort_order": r[2]} for r in rows],
        }


def _default_engine() -> Engine:
    try:
        from app.db.control.session import get_control_engine  # type: ignore[attr-defined]
        return get_control_engine()
    except (ImportError, AttributeError):
        pass
    from app.services.provisioning import _admin_url
    for name in ("payroll_control", "control", "payroll_ctrl"):
        try:
            eng = sa.create_engine(_admin_url(name), future=True)
            with eng.connect() as c:
                c.execute(sa.text("SELECT 1"))
            return eng
        except Exception:
            continue
    raise RuntimeError(
        "cannot locate control DB; pass --db-url or set CONTROL_DB_URL in the environment"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="statutory_loader")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name in ("validate", "confirm"):
        sp = sub.add_parser(name)
        sp.add_argument("file")
        sp.add_argument("--db-url")
        if name == "confirm":
            sp.add_argument("--typed-version", required=True)
            sp.add_argument("--actor")

    sp = sub.add_parser("end-date")
    sp.add_argument("--table-id", required=True)
    sp.add_argument("--new-end-date", required=True)
    sp.add_argument("--db-url")
    sp.add_argument("--actor")

    args = p.parse_args(argv)
    engine = sa.create_engine(args.db_url, future=True) if args.db_url else _default_engine()
    bootstrap_schema(engine)

    if args.cmd == "validate":
        doc = json.loads(Path(args.file).read_text(encoding="utf-8"))
        res = validate_document(doc)
        if not res.ok:
            for err in res.errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return 1
        current = _fetch_current_active(engine, doc["country_code"], doc["table_type"])
        diff = compute_diff(doc, current)
        print(f"OK. {diff.action}. {json.dumps(diff.to_dict())}")
        return 0

    if args.cmd == "confirm":
        doc = json.loads(Path(args.file).read_text(encoding="utf-8"))
        try:
            result = apply_document(engine, doc, actor_user_id=args.actor, typed_version=args.typed_version)
        except ValueError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2
        print(f"OK. loaded table_id={result['table_id']} diff={json.dumps(result['diff'])}")
        return 0

    if args.cmd == "end-date":
        try:
            result = end_date(engine, args.table_id, new_end_date=args.new_end_date, actor_user_id=args.actor)
        except ValueError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2
        print(f"OK. {json.dumps(result)}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())

# END OF FILE
