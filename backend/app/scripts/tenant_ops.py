"""Per-tenant operations: backup, restore, export, delete.

    backup  - pg_dump custom-format file + subscriber metadata sidecar
    restore - pg_restore --clean --if-exists into an existing tenant DB
    export  - POPIA access: full JSON export of every tenant table with
              EncryptedString columns decrypted under the tenant key
    delete  - POPIA erasure: drop the tenant database, null the encryption
              key, and mark the subscriber 'deleted' while keeping the
              subscriber row as a record of what was erased and when.

All destructive commands require --confirm <slug>. The backups directory
is mounted at /app/backups inside the api container.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.tenant_routing import get_head_revision, tenant_context
from app.db.base import Base  # noqa: F401  (ensures mapper registry exists)
from app.db.control.models import ControlAuditLog, Subscriber
from app.db.control.session import control_session
from app.db.tenant import models as tenant_models  # noqa: F401  (registers mappers)
from app.db.tenant.session import tenant_session

log = get_logger("app.scripts.tenant_ops")

BACKUP_DIR = Path(os.environ.get("TENANT_BACKUP_DIR", "/app/backups"))

TENANT_MODEL_ORDER = [
    "Company", "Branch", "Site", "Department", "Employee", "User",
    "UserScope", "EmployeePayHistory", "BiometricConsent",
    "BiometricEnrolment", "Device", "Setting", "Notification", "AuditLog",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _ConnParts:
    host: str
    port: int
    user: str
    password: str
    dbname: str


def _conn_parts(url: str) -> _ConnParts:
    normalised = url.replace("postgresql+psycopg://", "postgresql://")
    u = urlparse(normalised)
    if not u.hostname or not u.username or not u.password:
        raise RuntimeError(f"Cannot parse database URL: {url!r}")
    return _ConnParts(
        host=u.hostname,
        port=u.port or 5432,
        user=u.username,
        password=u.password,
        dbname=u.path.lstrip("/"),
    )


def _subscriber_or_fail(slug: str) -> Subscriber:
    with control_session() as session:
        sub = session.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
        if sub is None:
            raise SystemExit(f"Tenant '{slug}' not found")
        return sub


def _audit(actor: str, action: str, entity_id: str, detail: dict) -> None:
    with control_session() as session:
        session.add(
            ControlAuditLog(
                actor_role="ops",
                entity_type="subscriber",
                entity_id=entity_id,
                action=action,
                new_value={"actor": actor, **detail},
            )
        )


def _pg_env(parts: _ConnParts) -> dict[str, str]:
    env = os.environ.copy()
    env["PGPASSWORD"] = parts.password
    return env


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------


def cmd_backup(slug: str) -> int:
    sub = _subscriber_or_fail(slug)
    if not sub.tenant_db_name:
        raise SystemExit(f"Tenant '{slug}' has no tenant database")

    admin_url = get_settings().database_url_tenant_admin_template.format(
        tenant_db=sub.tenant_db_name
    )
    parts = _conn_parts(admin_url)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dump_path = BACKUP_DIR / f"{slug}_{ts}.dump"
    meta_path = BACKUP_DIR / f"{slug}_{ts}.json"

    log.info("tenant_ops.backup.start", slug=slug, db=sub.tenant_db_name, file=str(dump_path))
    subprocess.run(
        [
            "pg_dump",
            "-Fc",
            "-h", parts.host,
            "-p", str(parts.port),
            "-U", parts.user,
            "-d", parts.dbname,
            "-f", str(dump_path),
        ],
        check=True,
        env=_pg_env(parts),
    )

    meta = {
        "slug": slug,
        "subscriber_id": str(sub.id),
        "name": sub.name,
        "tenant_db_name": sub.tenant_db_name,
        "schema_version": sub.tenant_schema_version,
        "encryption_key_encrypted": sub.encryption_key_encrypted,
        "backed_up_at": ts,
        "dump_file": dump_path.name,
        "dump_bytes": dump_path.stat().st_size,
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    _audit("cli", "tenant.backup", str(sub.id), {"file": dump_path.name, "bytes": meta["dump_bytes"]})
    log.info(
        "tenant_ops.backup.done",
        slug=slug, file=str(dump_path), bytes=meta["dump_bytes"],
    )
    print(f"backup written: {dump_path} ({meta['dump_bytes']} bytes)")
    print(f"metadata written: {meta_path}")
    return 0


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


def cmd_restore(slug: str, file: Path, confirm: str) -> int:
    if confirm != slug:
        raise SystemExit("Restore requires --confirm <slug> matching the target slug")
    if not file.exists():
        raise SystemExit(f"Backup file not found: {file}")

    sub = _subscriber_or_fail(slug)
    if sub.status == "deleted":
        raise SystemExit(f"Tenant '{slug}' is deleted; cannot restore")
    if not sub.tenant_db_name:
        raise SystemExit(f"Tenant '{slug}' has no tenant database")

    admin_url = get_settings().database_url_tenant_admin_template.format(
        tenant_db=sub.tenant_db_name
    )
    parts = _conn_parts(admin_url)

    log.info("tenant_ops.restore.start", slug=slug, file=str(file))
    # --clean --if-exists drops and recreates objects; --no-owner keeps
    # the existing role assignments intact.
    subprocess.run(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "-h", parts.host,
            "-p", str(parts.port),
            "-U", parts.user,
            "-d", parts.dbname,
            str(file),
        ],
        check=True,
        env=_pg_env(parts),
    )

    _audit("cli", "tenant.restore", str(sub.id), {"file": file.name})
    log.info("tenant_ops.restore.done", slug=slug, file=str(file))
    print(f"restored {file} into {sub.tenant_db_name}")
    return 0


# ---------------------------------------------------------------------------
# export (POPIA access request)
# ---------------------------------------------------------------------------


def _json_default(obj: object) -> object:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, (bytes, bytearray)):
        return base64.b64encode(bytes(obj)).decode("ascii")
    return str(obj)


def _row_dict(instance: object) -> dict[str, object]:
    mapper = sa.inspect(type(instance)).mapper
    return {col.key: getattr(instance, col.key) for col in mapper.columns}


def cmd_export(slug: str) -> int:
    sub = _subscriber_or_fail(slug)
    if not sub.tenant_db_name:
        raise SystemExit(f"Tenant '{slug}' has no tenant database")

    ts = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = BACKUP_DIR / "exports" / f"{slug}_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Set the tenant key so EncryptedString columns decrypt transparently.
    with tenant_context(slug):
        with tenant_session(sub.tenant_db_name) as session:
            row_counts: dict[str, int] = {}
            for name in TENANT_MODEL_ORDER:
                model = getattr(tenant_models, name)
                rows = session.query(model).all()
                payload = [_row_dict(r) for r in rows]
                (out_dir / f"{model.__tablename__}.json").write_text(
                    json.dumps(payload, indent=2, default=_json_default),
                    encoding="utf-8",
                )
                row_counts[model.__tablename__] = len(rows)

            # Include alembic_version so the export records what schema it came from
            try:
                version = session.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                ).scalar()
            except Exception:
                version = None

    manifest = {
        "slug": slug,
        "subscriber_id": str(sub.id),
        "name": sub.name,
        "tenant_db_name": sub.tenant_db_name,
        "schema_version": version,
        "head_revision": get_head_revision(),
        "exported_at": ts,
        "row_counts": row_counts,
        "note": (
            "POPIA data access export. EncryptedString columns are decrypted "
            "under the tenant key. This file contains personal information and "
            "must be stored and transmitted with appropriate safeguards."
        ),
    }
    (out_dir / "_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=_json_default), encoding="utf-8"
    )

    _audit("cli", "tenant.export", str(sub.id), {"dir": str(out_dir), "tables": row_counts})
    log.info("tenant_ops.export.done", slug=slug, dir=str(out_dir), tables=row_counts)
    print(f"exported to {out_dir}")
    for tbl, n in row_counts.items():
        print(f"  {tbl}: {n} rows")
    return 0


# ---------------------------------------------------------------------------
# delete (POPIA erasure)
# ---------------------------------------------------------------------------


def cmd_delete(slug: str, confirm: str) -> int:
    if confirm != slug:
        raise SystemExit("Delete requires --confirm <slug> matching the target slug")

    sub = _subscriber_or_fail(slug)
    if sub.status == "deleted":
        print(f"tenant '{slug}' already deleted")
        return 0
    if not sub.tenant_db_name:
        raise SystemExit(f"Tenant '{slug}' has no tenant database to drop")

    db_name = sub.tenant_db_name
    sub_id = str(sub.id)

    admin_engine = create_engine(
        get_settings().database_url_tenant_admin_template.format(tenant_db="postgres"),
        isolation_level="AUTOCOMMIT",
        future=True,
    )
    try:
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :d AND pid <> pg_backend_pid()"
                ),
                {"d": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    finally:
        admin_engine.dispose()

    with control_session() as session:
        row = session.query(Subscriber).filter(Subscriber.slug == slug).one()
        row.status = "deleted"
        row.provisioning_status = "deleted"
        row.tenant_db_name = None
        row.tenant_schema_version = None
        # POPIA erasure: nulling the encryption key means any stray ciphertext
        # in a forgotten backup is unrecoverable.
        row.encryption_key_encrypted = "DELETED"

    _audit("cli", "tenant.delete", sub_id, {"dropped_db": db_name})
    log.info("tenant_ops.delete.done", slug=slug, dropped_db=db_name)
    print(f"tenant '{slug}' deleted (database dropped, subscriber row marked 'deleted')")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.tenant_ops",
        description="Per-tenant backup / restore / export / delete.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_b = sub.add_parser("backup", help="pg_dump a tenant DB to /app/backups")
    p_b.add_argument("--slug", required=True)

    p_r = sub.add_parser("restore", help="pg_restore a backup into an existing tenant DB")
    p_r.add_argument("--slug", required=True)
    p_r.add_argument("--file", required=True, type=Path)
    p_r.add_argument("--confirm", required=True,
                     help="Must equal --slug to prove intent")

    p_e = sub.add_parser("export", help="Full JSON export (POPIA access request)")
    p_e.add_argument("--slug", required=True)

    p_d = sub.add_parser("delete", help="Drop tenant DB and mark subscriber deleted")
    p_d.add_argument("--slug", required=True)
    p_d.add_argument("--confirm", required=True,
                     help="Must equal --slug to prove intent")

    args = parser.parse_args(argv)
    configure_logging()

    if args.cmd == "backup":
        return cmd_backup(args.slug)
    if args.cmd == "restore":
        return cmd_restore(args.slug, args.file, args.confirm)
    if args.cmd == "export":
        return cmd_export(args.slug)
    if args.cmd == "delete":
        return cmd_delete(args.slug, args.confirm)
    return 2


if __name__ == "__main__":
    sys.exit(main())