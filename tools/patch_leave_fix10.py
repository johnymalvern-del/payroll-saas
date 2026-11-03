"""L2d fix10: seed CountryCalendar for ZA/2026 in the 10 approval tests that
hit the attendance path via _final_approval_side_effects -> _holiday_set_for.

- _holiday_set_for -> _load_holiday_set fail-closed if no rows for (country, year);
  same for missing Company. Fix is test-side seeding; code stays fail-closed.
- New local _mk_cal(session, year) uses flush (not commit), dedupes on
  (country_code, holiday_date) — matches the pattern of _mk_cal in
  test_attendance.py / test_exceptions.py, but rollback-safe for the
  _leave_session_shared fixture.
- 8 fix9 tests: add _mk_cal(2026) next to _mk_company.
- 2 tests (capture_self_approve_with_note, revert_on_cancel_approved): add
  both _mk_company + _mk_cal before _setup_two_approvers.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
T_APPROVAL = ROOT / "backend" / "tests" / "test_leave_approval.py"

tasrc = T_APPROVAL.read_text(encoding="utf-8")

# --- 1. Insert _mk_cal helper before _mk_emp ---
if "def _mk_cal(session, year):" not in tasrc:
    anchor = "def _mk_emp(session"
    idx = tasrc.find(anchor)
    if idx < 0:
        raise SystemExit("FATAL: _mk_emp anchor not found")
    helper = '''def _mk_cal(session, year):
    from app.db.tenant.models.attendance import CountryCalendar
    target = date(year, 12, 25)
    if session.scalar(select(CountryCalendar).where(
        CountryCalendar.country_code == "ZA",
        CountryCalendar.holiday_date == target,
    )) is None:
        session.add(CountryCalendar(
            country_code="ZA", holiday_date=target,
            name="Xmas", source_ref="test",
        ))
        session.flush()


'''
    tasrc = tasrc[:idx] + helper + tasrc[idx:]
    print("_mk_cal helper inserted")
else:
    print("_mk_cal already present")

# --- 2. 8 fix9 tests: add _mk_cal(2026) after inline _mk_company ---
company_tests = [
    "test_approve_single_step_approves_and_adjusts",
    "test_step_already_decided_refused",
    "test_advance_skips_step",
    "test_decide_shortcut_on_submitted",
    "test_attendance_outcome_leave",
    "test_attendance_outcome_sick_when_code_configured",
    "test_no_absent_expected_after_approval",
    "test_requires_approval_false_auto_approves",
]
for name in company_tests:
    old = f"def {name}(session):\n    _mk_company(session)\n"
    new = f"def {name}(session):\n    _mk_company(session)\n    _mk_cal(session, 2026)\n"
    if new in tasrc:
        print(f"{name}: already patched")
        continue
    if old in tasrc:
        tasrc = tasrc.replace(old, new, 1)
        print(f"{name}: _mk_cal added")
    else:
        print(f"WARN: {name} pattern not found")

# --- 3. Two tests missing Company entirely ---
for name in ("test_capture_self_approve_with_note",
             "test_revert_on_cancel_approved"):
    old = f"def {name}(session):\n    emp, hr_user, admin, t = _setup_two_approvers(session)\n"
    new = (
        f"def {name}(session):\n"
        f"    _mk_company(session)\n"
        f"    _mk_cal(session, 2026)\n"
        f"    emp, hr_user, admin, t = _setup_two_approvers(session)\n"
    )
    if new in tasrc:
        print(f"{name}: already patched")
        continue
    if old in tasrc:
        tasrc = tasrc.replace(old, new, 1)
        print(f"{name}: _mk_company + _mk_cal added")
    else:
        print(f"WARN: {name} pattern not found")

T_APPROVAL.write_text(tasrc, encoding="utf-8")

# --- 4. Verify occurrences ---
print("=== _mk_cal calls in file ===")
import re
for m in re.finditer(r"_mk_cal\(session, (\d+)\)", tasrc):
    ln = tasrc[:m.start()].count("\n") + 1
    print(f"  line {ln}: _mk_cal(session, {m.group(1)})")

print("=== _mk_company calls in file ===")
for m in re.finditer(r"_mk_company\(session\)", tasrc):
    ln = tasrc[:m.start()].count("\n") + 1
    print(f"  line {ln}: _mk_company(session)")