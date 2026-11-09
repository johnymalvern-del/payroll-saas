"""Fix seed: set T001 DOB, distinguish tax-table gate from other errors."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "tools" / "milestone1_seed.py"
s = P.read_text(encoding="utf-8")

# --- 1. Set T001 DOB in section B ---
old_b_anchor = '''    hist = s.scalar(
        select(EmployeePayHistory).where(
            EmployeePayHistory.employee_id == emp.id,
            EmployeePayHistory.status == "approved",
        )
    )
'''
new_b_anchor = '''    # DOB required for _resolve_age with age_reference_date="date_of_birth"
    if emp.date_of_birth is None:
        emp.date_of_birth = date(1990, 5, 15)
        s.flush()
        print(f"  set date_of_birth = 1990-05-15 (demo)")
    else:
        print(f"  date_of_birth already = {emp.date_of_birth}")

    hist = s.scalar(
        select(EmployeePayHistory).where(
            EmployeePayHistory.employee_id == emp.id,
            EmployeePayHistory.status == "approved",
        )
    )
'''
if old_b_anchor not in s:
    raise SystemExit("FATAL: section B anchor not matched")
s = s.replace(old_b_anchor, new_b_anchor, 1)

# --- 2. Replace the misleading exception handling around build_pipeline_config ---
old_try = '''    try:
        cfg = pr.build_pipeline_config(s, emp, period.pay_date)
        print(f"  SUCCESS: pipeline config OK")
        print(f"    periods_per_year={cfg.periods_per_year}")
        print(f"    age={cfg.employee_age}")
        print(f"    sdl_applies={cfg.sdl_applies}")
        print(f"    uif_rows={len(cfg.uif_rows or [])}")
        print(f"    sdl_rows={len(cfg.sdl_rows or [])}")
        print(f"    retirement_rows={len(cfg.retirement_rows or [])}")
    except Exception as e:
        print(f"  BLOCKED: {type(e).__name__}: {e}")
        print()
        print("  >>> Milestone 1 DATA SETUP IS COMPLETE.")
        print("  >>> Payroll run is BLOCKED on the statutory table step.")
        print("  >>> This is the Milestone 6 dependency (SARs tables /")
        print("  >>> authorised placeholder bootstrap must be loaded).")
        print("  >>> Re-running this seed after M6 completes will finish")
        print("  >>> the run to finalise without any further data changes.")
        sys.exit(0)
'''
new_try = '''    try:
        cfg = pr.build_pipeline_config(s, emp, period.pay_date)
        print(f"  SUCCESS: pipeline config OK")
        print(f"    periods_per_year={cfg.periods_per_year}")
        print(f"    age={cfg.employee_age}")
        print(f"    sdl_applies={cfg.sdl_applies}")
        print(f"    uif_rows={len(cfg.uif_rows or [])}")
        print(f"    sdl_rows={len(cfg.sdl_rows or [])}")
        print(f"    retirement_rows={len(cfg.retirement_rows or [])}")
    except Exception as e:
        code = getattr(e, "code", None)
        msg = str(e)
        print(f"  FAILED: {type(e).__name__} code={code!r} msg={msg}")
        print()

        # Diagnose the actual blocker
        if "date_of_birth" in msg.lower():
            print("  >>> BLOCKED: employee.date_of_birth is required")
            print("  >>> (age_reference_date='date_of_birth' needs it)")
            print("  >>> This seed should have set it in section B.")
            print("  >>> If this message persists, re-check section B output.")
            sys.exit(1)
        elif code in (
            "tax_tables_missing", "tax_tables_refused",
            "statutory_table_missing", "uif_missing", "sdl_missing",
            "retirement_limit_missing",
        ) or "statutory" in msg.lower() or "tax_table" in msg.lower():
            print("  >>> MILESTONE 1 BLOCKED ON MILESTONE 6.")
            print("  >>> PayrollSettings, rate rules, formulas, employee,")
            print("  >>> and attendance setup are all COMPLETE (sections A-H).")
            print("  >>> The refusal is from the statutory table pipeline.")
            print("  >>> Real SARS tables must be loaded (Milestone 6).")
            print("  >>> Re-running this seed after M6 will complete the run")
            print("  >>> to finalise with no further data changes needed.")
            sys.exit(0)
        elif code == "settings_missing":
            print("  >>> Settings row not created — section D needs review.")
            sys.exit(1)
        else:
            print(f"  >>> Unclassified blocker code={code!r}.")
            print("  >>> Stopping. Data setup A-H is complete.")
            sys.exit(1)
'''
if old_try not in s:
    raise SystemExit("FATAL: try/except block not matched")
s = s.replace(old_try, new_try, 1)

# --- 3. Also fix the exit message at section J (only reached if cfg succeeded) ---
# (no change needed — J only runs when build_pipeline_config succeeded)

P.write_text(s, encoding="utf-8")
print("patched: DOB set in B, error classification in I")