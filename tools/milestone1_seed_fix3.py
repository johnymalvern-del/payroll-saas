"""Fix seed: send device_now_at_send = now() so offset_ms ≈ 0."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "tools" / "milestone1_seed.py"
s = P.read_text(encoding="utf-8")

# ---- 1. Add text import (for punch diagnostic) ----
if "from sqlalchemy import create_engine, func, select\n" in s:
    s = s.replace(
        "from sqlalchemy import create_engine, func, select\n",
        "from sqlalchemy import create_engine, func, select, text\n",
        1,
    )
    print("added `text` to sqlalchemy imports")
else:
    print("text import may already be present")

# ---- 2. Add device_now_at_send to punch body ----
old_punch = '''            cid = uuid.uuid5(uuid.NAMESPACE_DNS, f"m1-{emp.id}-{wd}-{direction}")
            s_api, resp = api(
                "POST", "/punches",
                {"client_punch_id": str(cid), "employee_id": str(emp.id),
                 "device_time": time_str, "method": "fingerprint"},
                tok=token, extra={"X-Device-Key": dev_key},
            )
'''
new_punch = '''            cid = uuid.uuid5(uuid.NAMESPACE_DNS, f"m1-{emp.id}-{wd}-{direction}")
            now_iso = datetime.now(timezone.utc).isoformat()
            s_api, resp = api(
                "POST", "/punches",
                {"client_punch_id": str(cid), "employee_id": str(emp.id),
                 "device_time": time_str,
                 "device_now_at_send": now_iso,
                 "method": "fingerprint"},
                tok=token, extra={"X-Device-Key": dev_key},
            )
'''
if old_punch not in s:
    raise SystemExit("FATAL: punch body pattern not matched")
s = s.replace(old_punch, new_punch, 1)
print("patched: device_now_at_send = now() added to punch body")

# ---- 3. Add punch diagnostic at end of section G ----
old_g_end = '''        if ok:
            print(f"  {wd}: punched")
        time.sleep(0.3)

    # ============================================================
    step("H. State summary + attendance_earning_map")
'''
new_g_end = '''        if ok:
            print(f"  {wd}: punched")
        time.sleep(0.3)

    # Diagnostic: show resulting effective_time vs device_time
    s.expire_all()
    punch_check = s.execute(
        text(
            "SELECT effective_time, device_time, offset_ms "
            "FROM punch WHERE employee_id = :eid "
            "AND device_time::date BETWEEN '2026-11-04' AND '2026-11-10' "
            "ORDER BY device_time"
        ),
        {"eid": str(emp.id)},
    ).all()
    print(f"  punch timestamp verification ({len(punch_check)} rows):")
    for pc in punch_check:
        print(f"    eff={pc[0]} dev={pc[1]} offset_ms={pc[2]}")

    # ============================================================
    step("H. State summary + attendance_earning_map")
'''
if old_g_end not in s:
    raise SystemExit("FATAL: section G end pattern not matched")
s = s.replace(old_g_end, new_g_end, 1)
print("patched: punch timestamp diagnostic added to section G")

P.write_text(s, encoding="utf-8")
print("done")