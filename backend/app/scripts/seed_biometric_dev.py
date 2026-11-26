"""DEVELOPMENT ONLY: create an approval record so enrolment can be exercised.

This exists so the pipeline can be tested end to end before a real approval is
signed. It is NOT a compliance control and it must never be run against a
production control database.

What it does, and what it deliberately does not:

    creates   one biometric_approval row with status='approved'
    records   the SHA-256 of docs/BIOMETRIC_APPROVAL_RECORD_DRAFT.md, so the
              gate's document check passes
    refuses   if the subscriber is not a test-looking slug, unless --force
    does not  set BIOMETRIC_ENROLMENT_ENABLED -- that stays an operator action
    does not  install a provider -- BIOMETRIC_PROVIDER must also be set

So three things are needed to enrol anyone, and this script provides one:

    python -m app.scripts.seed_biometric_dev --slug tenant-demo
    set BIOMETRIC_ENROLMENT_ENABLED=1
    set BIOMETRIC_PROVIDER=face

A row created here is indistinguishable from a signed one at the database level
once the document hash matches. That is by design -- the gate checks evidence,
not intent -- which is exactly why this script must not reach production.

Usage:
    python -m app.scripts.seed_biometric_dev --slug tenant-demo --check
    python -m app.scripts.seed_biometric_dev --slug tenant-demo --confirm
    python -m app.scripts.seed_biometric_dev --slug tenant-demo --confirm --remove
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

from app.db.control.models import BiometricApproval, Subscriber
from app.db.control.session import control_session

DEFAULT_DOC = Path("docs/BIOMETRIC_APPROVAL_RECORD_DRAFT.md")

# Slugs that look like a real customer are refused without --force. A mistake
# here writes a row that opens a legal gate, so the default must be to stop.
_TEST_MARKERS = ("demo", "test", "dev", "local", "sandbox")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--biometric-type", default="face", choices=["face", "fingerprint", "both"])
    ap.add_argument("--days", type=int, default=30, help="retention days recorded")
    ap.add_argument("--document", default=str(DEFAULT_DOC))
    ap.add_argument("--check", action="store_true", help="show what would happen")
    ap.add_argument("--confirm", action="store_true", help="actually write")
    ap.add_argument("--remove", action="store_true", help="delete the row instead")
    ap.add_argument("--force", action="store_true", help="allow a non-test slug")
    args = ap.parse_args()

    looks_like_test = any(m in args.slug.lower() for m in _TEST_MARKERS)
    if not looks_like_test and not args.force:
        print(
            f"REFUSED: slug {args.slug!r} does not look like a development "
            f"tenant. Pass --force only if you are certain."
        )
        return 2

    doc = Path(args.document)
    if not doc.exists():
        print(f"REFUSED: approval document not found at {doc}")
        return 2

    digest = _sha256(doc)

    with control_session() as session:
        sub = session.query(Subscriber).filter(Subscriber.slug == args.slug).one_or_none()
        if sub is None:
            print(f"REFUSED: no subscriber with slug {args.slug!r}")
            return 2

        existing = (
            session.query(BiometricApproval)
            .filter(
                BiometricApproval.subscriber_id == sub.id,
                BiometricApproval.biometric_type == args.biometric_type,
            )
            .one_or_none()
        )

        if args.remove:
            if existing is None:
                print("nothing to remove")
                return 0
            if not args.confirm:
                print(f"would remove approval {existing.id}")
                return 0
            session.delete(existing)
            session.commit()
            print(f"removed approval for {args.slug} / {args.biometric_type}")
            return 0

        if existing is not None:
            print(f"an approval already exists: id={existing.id} status={existing.status}")
            print("use --remove to clear it first, or --check to inspect")
            return 0

        print(f"subscriber : {sub.slug} ({sub.id})")
        print(f"type       : {args.biometric_type}")
        print(f"document   : {doc}")
        print(f"sha256     : {digest}")
        print(f"effective  : {date.today()} .. none")

        if args.check or not args.confirm:
            print("\ndry run -- pass --confirm to write")
            return 0

        session.add(
            BiometricApproval(
                id=uuid.uuid4(),
                subscriber_id=sub.id,
                status="approved",
                biometric_type=args.biometric_type,
                approved_by_company="DEV SEED — not a signature",
                approved_by_counsel="DEV SEED — not a signature",
                signed_at=None,
                effective_from=date.today() - timedelta(days=1),
                effective_to=None,
                record_sha256=digest,
                scope_employee_ids=None,
                scope_site_ids=None,
                retention_days=args.days,
                notes="DEVELOPMENT SEED. Not a real approval. Delete before go-live.",
                row_version=1,
            )
        )
        session.commit()

    print("\nwritten. A development approval is now in place.")
    print("This is NOT a real approval. Remove it with --remove before go-live.")
    print("\nEnrolment still needs:")
    print("    set BIOMETRIC_ENROLMENT_ENABLED=1")
    print("    set BIOMETRIC_PROVIDER=face")
    return 0


if __name__ == "__main__":
    sys.exit(main())