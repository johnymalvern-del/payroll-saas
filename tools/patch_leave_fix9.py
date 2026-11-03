"""L2d fix9: 4 groups + trace.

1. build_approval_chain: subject-based exclusion (approver.employee_id == employee.id)
   instead of submitter.id.  Enables capture-HR to remain in chain; subject still excluded.
2. test_leave_approval.py: import _mk_company from test_payroll_attendance_earnings (the
   helper used by test_payroll_attendance_earnings/_payroll_b4_end_to_end/_payroll_finalise_ack).
3. Inline _mk_company(session) into the 8 approval tests hitting the Company row.
4. Split skipped test_self_approval_refused into 2 real tests (self-only submit -> 409
   no_eligible_approver; subject decides -> 403 self_approval_forbidden).
5. test_revert_on_cancel_approved: 2099 -> 2026-12-01 (matches existing _mk_balance 2026 cycle).
6. Report test counts.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEAVE_ENGINE = ROOT / "backend" / "app" / "payroll_engine" / "leave.py"
T_APPROVAL = ROOT / "backend" / "tests" / "test_leave_approval.py"
T_REQUESTS = ROOT / "backend" / "tests" / "test_leave_requests.py"

# --- 1. subject-based exclusion ---
lesrc = LEAVE_ENGINE.read_text(encoding="utf-8")
old_line = "        if approver.id == submitter.id:\n"
new_line = "        if approver.employee_id == employee.id:\n"
if old_line not in lesrc:
    raise SystemExit("FATAL: submitter.id exclusion not found")
lesrc = lesrc.replace(old_line, new_line, 1)
LEAVE_ENGINE.write_text(lesrc, encoding="utf-8")
print("leave.py: subject-based exclusion (approver.employee_id == employee.id)")

# --- 2. import _mk_company in test_leave_approval.py ---
tasrc = T_APPROVAL.read_text(encoding="utf-8")
if "from test_payroll_attendance_earnings import _mk_company" not in tasrc:
    import_block = (
        "\ntry:\n"
        "    from test_payroll_attendance_earnings import _mk_company\n"
        "except ImportError:\n"
        "    from tests.test_payroll_attendance_earnings import _mk_company\n"
    )
    idx = tasrc.find("\ndef _admin(")
    if idx > 0:
        tasrc = tasrc[:idx] + import_block + tasrc[idx:]
    else:
        tasrc = import_block + tasrc
    print("test_leave_approval.py: _mk_company import added")
else:
    print("test_leave_approval.py: _mk_company import already present")

# --- 3. inline _mk_company in 8 approval tests ---
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
    sig = f"def {name}(session):\n"
    if sig not in tasrc:
        print(f"WARN: {name} signature not found")
        continue
    if f"def {name}(session):\n    _mk_company(session)" in tasrc:
        print(f"{name}: _mk_company already inline")
        continue
    idx = tasrc.find(sig) + len(sig)
    tasrc = tasrc[:idx] + "    _mk_company(session)\n" + tasrc[idx:]
    print(f"{name}: inline _mk_company added")

# --- 4. split test_self_approval_refused ---
old_self = re.compile(
    r"def test_self_approval_refused\(session\):.*?(?=\n\ndef test_step_already_decided_refused)",
    re.S,
)
m = old_self.search(tasrc)
if m:
    new_self = '''def test_self_only_chain_refused_at_submit(session):
    _mk_company(session)
    hr_emp = _mk_emp(session, code="HR-SOLO")
    hr_user = _mk_user_for(session, hr_emp, "hr")
    t = _mk_type(session, approval_chain=["hr"])
    _mk_balance(session, hr_emp, t)
    r = create_leave_request(
        LeaveRequestIn(
            employee_id=hr_emp.id, leave_type_id=t.id,
            from_date=date(2026, 6, 1), to_date=date(2026, 6, 1),
        ),
        session, hr_user,
    )
    with pytest.raises(AppError) as e:
        submit_leave_request(r.id, session, hr_user)
    assert e.value.code == "no_eligible_approver"


def test_self_approval_refused(session):
    _mk_company(session)
    emp = _mk_emp(session, code="SUBJ")
    emp_user = _mk_user_for(session, emp, "payroll_admin")
    hr_emp = _mk_emp(session, code="HR-OTHER")
    hr_user = _mk_user_for(session, hr_emp, "hr")
    t = _mk_type(session, approval_chain=["hr"])
    _mk_balance(session, emp, t)
    admin = _admin(session)
    r = create_leave_request(
        LeaveRequestIn(
            employee_id=emp.id, leave_type_id=t.id,
            from_date=date(2026, 6, 1), to_date=date(2026, 6, 1),
        ),
        session, admin,
    )
    submit_leave_request(r.id, session, admin)
    step = session.scalar(select(LeaveApprovalStep).where(
        LeaveApprovalStep.leave_request_id == r.id,
        LeaveApprovalStep.status == "pending",
    ))
    assert step is not None
    assert step.approver_user_id == hr_user.id
    with pytest.raises(AppError) as e:
        decide_step(r.id, step.id, StepDecideIn(approve=True), session, emp_user)
    assert e.value.code == "self_approval_forbidden"
'''
    tasrc = tasrc[:m.start()] + new_self + tasrc[m.end():]
    print("test_self_approval_refused: split into 2 real tests")
else:
    print("WARN: test_self_approval_refused block not found")

# --- 5. 2099 -> 2026-12-01 ---
old_d = "from_date=date(2099, 6, 1), to_date=date(2099, 6, 1),"
new_d = "from_date=date(2026, 12, 1), to_date=date(2026, 12, 1),"
if old_d in tasrc:
    tasrc = tasrc.replace(old_d, new_d, 1)
    print("test_revert_on_cancel_approved: 2099 -> 2026-12-01")
else:
    print("WARN: 2099 date not found")

T_APPROVAL.write_text(tasrc, encoding="utf-8")

# --- 6. count ---
print("=== test counts ===")
for p in (T_REQUESTS, T_APPROVAL):
    ids = re.findall(r"^def (test_[a-z0-9_]+)\(session\)", p.read_text(encoding="utf-8"), re.M)
    print(f"  {p.name}: {len(ids)}")
    for i, t in enumerate(ids, 1):
        print(f"    {i}. {t}")