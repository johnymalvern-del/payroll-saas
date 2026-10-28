"""Close Chapter 2A: verify STATE.md, stage backend + docs, commit once."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\xampp\htdocs\Payroll")


def fail(msg: str) -> None:
    print(f"STOP: {msg}")
    sys.exit(1)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    print("$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)


# 1. STATE.md must exist and end with the marker.
state = ROOT / "docs" / "STATE.md"
if not state.exists():
    fail("docs/STATE.md does not exist; paste its content in VS Code and save first")
text = state.read_text(encoding="utf-8")
last = [l for l in text.splitlines() if l.strip()][-1] if text.strip() else ""
if last != "# END OF FILE":
    fail(f"STATE.md does not end with '# END OF FILE' (last: {last!r})")
print(f"STATE.md ok: {len(text)} bytes, {len(text.splitlines())} lines")

# 2. Clean up any diagnostic leftovers.
leftovers = [
    "_2a7.log", "_2a7.out", "_2a7.err", "_2a7_patch.py", "_2a_commit_msg.txt",
    "scripts/2A-7.ps1", "scripts/2A-7a.ps1", "scripts/2A-7b.ps1", "scripts/2A-7c.ps1",
    "scripts/run_2a7_diagnostic.ps1", "scripts/_2a7_patch.py", "scripts/2A-close.ps1",
]
for rel in leftovers:
    p = ROOT / rel
    if p.exists():
        p.unlink()
        print(f"removed: {rel}")

# 3. Write the commit message to a temp file, one commit covers the chapter.
msg_lines = [
    "Chapter 2A: attendance foundation",
    "",
    "Migration 0012 (amended): 8 tables + a device ALTER. Punch is append-only",
    "via REVOKE UPDATE/DELETE plus a BEFORE UPDATE OR DELETE trigger. Grants for",
    "the 7 new tables applied at the end of 0012, after 0001's blanket GRANT.",
    "",
    "Models: Shift, ShiftRateRule, WorkPattern (with days relationship),",
    "WorkPatternDay, PublicHolidayTenant, Punch, EmployeeWorkPattern. Device",
    "stays in devices.py; 0012 adds row_version and converts ix_device_api_key_hash",
    "to a UNIQUE uq_device_api_key_hash. tests/test_schema_drift.py compares every",
    "non-control table's model columns against information_schema on the tenant DB.",
    "",
    "Endpoints registered in app/api/v1/__init__.py: /shifts (5),",
    "/shifts/{id}/rate-rules (3), /work-patterns (5), /employees/{id}/work-patterns",
    "(3), /public-holidays (4), /devices (5 + rotate-key), /punches (list, single,",
    "batch, GET by id).",
    "",
    "Punch pure functions in app/api/v1/punch_service.py: A2 timing, A3",
    "idempotency (canonical_payload_hash over identity fields), A6 photo and",
    "raw_payload validation, A4 classifiers. All pure; no DB, no HTTP.",
    "",
    "Permissions: ATTENDANCE_VIEW added per section 6, granted to employee,",
    "manager, hr, payroll_admin; auditor NOT granted. ORG_VIEW and ORG_MANAGE",
    "transcribed into test_permissions.py's independent matrix (they existed in",
    "code since 1C.5 but were missing from the matrix). The matrix now covers",
    "23 permissions x 5 roles.",
    "",
    "Scope: apply_scope on the punch list; assert_in_scope on GET /punches/{id}.",
    "Out-of-scope returns 404 record_not_found.",
    "",
    "Production bug fixed in app/core/errors.py: validation_exception_handler",
    "returned Pydantic's exc.errors() raw, which contains ctx.error as a",
    "ValueError instance and cannot be JSON-serialised. Any endpoint with a",
    "custom @field_validator raising ValueError returned 500 instead of 422.",
    "Fixed by stripping ctx from each error dict; msg is kept.",
    "",
    "Tests: +150. 419 before 2A, 569 after. run_tests.ps1 green.",
    "",
    "Open items carried into 2B (see docs/STATE.md): 5 MB batch body cap,",
    "photo happy path, sites.py site_in_use must count punches and devices,",
    "work_pattern audit snapshot, btree_gist EXCLUDE constraints,",
    "Employee.work_pattern_id and default_shift_id deprecation.",
]
msg_file = ROOT / "_2a_commit_msg.txt"
msg_file.write_text("\n".join(msg_lines) + "\n", encoding="utf-8")

# 4. Stage and commit.
r = run(["git", "add", "-A", "backend"])
if r.returncode != 0:
    fail(f"git add -A backend failed: {r.stderr.strip()}")
r = run(["git", "add", "docs/STATE.md"])
if r.returncode != 0:
    fail(f"git add docs/STATE.md failed: {r.stderr.strip()}")

r = run(["git", "diff", "--cached", "--name-only"])
staged = [x for x in r.stdout.splitlines() if x.strip()]
print(f"staged files: {len(staged)}")
for s in staged:
    print(f"  {s}")

if not staged:
    fail("nothing staged; the working tree has no changes to commit")

r = run(["git", "commit", "-F", str(msg_file)])
msg_file.unlink()
if r.returncode != 0:
    fail(f"git commit failed: {r.stderr.strip()}")
print(r.stdout.strip())

r = run(["git", "rev-parse", "--short", "HEAD"])
print(f"COMMIT 2A: {r.stdout.strip()}")

r = run(["git", "log", "--oneline", "-3"])
print(r.stdout)

r = run(["git", "status", "--porcelain"])
print("--- working tree (empty = clean) ---")
print(r.stdout)

print("2A CLOSE PASS")