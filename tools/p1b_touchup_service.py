"""Phase 1B touch-up — savepoint + IntegrityError handling in create_decision_record."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "backend" / "app" / "services" / "intelligence_service.py"
s = P.read_text(encoding="utf-8")

# 1. Add IntegrityError import if missing
if "from sqlalchemy.exc import IntegrityError" not in s:
    anchor = "from sqlalchemy import select\n"
    if anchor not in s:
        raise SystemExit("FATAL: 'from sqlalchemy import select' not found")
    s = s.replace(anchor, anchor + "from sqlalchemy.exc import IntegrityError\n", 1)
    print("added IntegrityError import")
else:
    print("IntegrityError already imported")

# 2. Locate the decision-insert add/flush and replace with savepoint block
marker = "decision_type=decision_type,"
marker_idx = s.find(marker)
if marker_idx < 0:
    raise SystemExit("FATAL: 'decision_type=decision_type' not found — file drifted")

add_idx = s.find("    db.add(decision)\n", marker_idx)
if add_idx < 0:
    raise SystemExit("FATAL: 'db.add(decision)' after marker not found")

flush_end = add_idx + len("    db.add(decision)\n")
if s[flush_end : flush_end + len("    db.flush()\n")] != "    db.flush()\n":
    raise SystemExit("FATAL: expected 'db.flush()' after 'db.add(decision)'")

old_block = "    db.add(decision)\n    db.flush()\n"
if s[add_idx : add_idx + len(old_block)] != old_block:
    raise SystemExit(f"FATAL: unexpected block: {s[add_idx:add_idx+len(old_block)]!r}")

new_block = '''    # Wrap the decision insert in a savepoint so a concurrent duplicate
    # (same workflow + idempotency_key) is caught and handled without
    # rolling back the caller's surrounding transaction.
    _sp = db.begin_nested()
    try:
        db.add(decision)
        db.flush()
        _sp.commit()
    except IntegrityError as exc:
        _sp.rollback()
        _msg = (
            str(exc.orig) if getattr(exc, "orig", None) else str(exc)
        ).lower()
        if idempotency_key is not None and (
            "uq_intelligence_decision_idempotency" in _msg
            or ("unique" in _msg and "idempotency" in _msg)
        ):
            _existing = db.scalar(
                select(IntelligenceDecision).where(
                    IntelligenceDecision.workflow == workflow,
                    IntelligenceDecision.idempotency_key == idempotency_key,
                )
            )
            if _existing is not None:
                if _existing.evidence_snapshot_id is not None:
                    _snap = db.get(
                        IntelligenceEvidenceSnapshot,
                        _existing.evidence_snapshot_id,
                    )
                    try:
                        _candidate_hash = _sha256_hex(
                            _canonical_serialise(
                                _sanitise_snapshot(evidence_payload)
                            )
                        )
                    except AppError:
                        _candidate_hash = None
                    if _snap is not None and _candidate_hash == _snap.sha256_hex:
                        return _existing
                raise AppError(
                    "idempotency_key_conflict",
                    f"Idempotency key {idempotency_key!r} already used "
                    f"with different payload",
                    409,
                )
        # Not an idempotency conflict — re-raise untouched
        raise
'''

s = s[:add_idx] + new_block + s[flush_end + len("    db.flush()\n") :]
P.write_text(s, encoding="utf-8")
print("patched create_decision_record with savepoint + IntegrityError recovery")