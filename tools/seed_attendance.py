"""Seed punches for T001-T010. Fix v5: use method='fingerprint' (valid, no
photo required, no StorageDep write). Avoids the 500 triggered by code+photo
(that is a separate backend bug — file it, do not debug it here)."""
import json, sys, uuid
import urllib.request, urllib.error
from datetime import date, timedelta

BASE = "http://localhost:8000/api/v1"
H = {"Content-Type": "application/json", "X-Tenant-Slug": "tenant-demo"}


def call(m, p, b=None, tok=None, extra=None):
    h = dict(H)
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    if extra:
        h.update(extra)
    data = json.dumps(b).encode() if b is not None else None
    try:
        r = urllib.request.urlopen(urllib.request.Request(BASE + p, data=data, headers=h, method=m))
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:700]
    except Exception as e:
        return 0, str(e)


s, body = call("POST", "/auth/login", {"identifier": "admin", "password": "devpass_admin"})
if s != 200:
    print(f"Login failed: {s} {body}"); sys.exit(1)
token = body["access_token"]

s, eb = call("GET", "/employees?limit=500&status=active", tok=token)
emps = [e for e in eb["items"] if e["employee_code"].startswith("T0")]
s, sb = call("GET", "/sites?limit=100", tok=token)
site_ids = [x["id"] for x in sb.get("items", [])]
print(f"Test employees: {len(emps)}  Sites: {len(site_ids)}\n")

# assign sites if missing
for i, e in enumerate(emps):
    if e.get("site_id"):
        continue
    sid = site_ids[i % len(site_ids)]
    s, _ = call("PATCH", f"/employees/{e['id']}",
                {"row_version": e["row_version"], "site_id": sid}, tok=token)
    if s == 200:
        e["site_id"] = sid
        print(f"  assigned site to {e['employee_code']}")

# group by site
by_site = {}
for e in emps:
    if e.get("site_id"):
        by_site.setdefault(e["site_id"], []).append(e)

# device key per site (fingerprint method does not need allows_code_only)
keys = {}
for sid in by_site:
    dev_name = f"Seed device {sid[:8]}"
    s, devlist = call("GET", "/devices?limit=100", tok=token)
    found = None
    if s == 200:
        for d in devlist.get("items", []):
            if d["name"] == dev_name:
                found = d; break
    if found:
        s, rot = call("POST", f"/devices/{found['id']}/rotate-key", tok=token)
        if s == 200:
            keys[sid] = rot["api_key"]
            print(f"  device {sid[:8]}: rotated")
    else:
        s, created = call("POST", "/devices", {
            "site_id": sid, "name": dev_name, "device_type": "usb_fingerprint",
        }, tok=token)
        if s in (200, 201):
            keys[sid] = created["api_key"]
            print(f"  device {sid[:8]}: created")
        else:
            print(f"  device {sid[:8]}: FAILED {s} {str(created)[:120]}")

# probe — fingerprint first (no photo), fallback to code (with photo)
TINY_PHOTO = "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAEf/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABD/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/EH//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/EH//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EH//2Q=="

_WORKING = None
def probe():
    global _WORKING
    emp = next(iter(by_site.values()))[0]
    sid = emp["site_id"]
    dt = "2026-10-15T08:00:00+02:00"  # well outside seeded range
    trials = [
        ("fingerprint", None),
        ("code", TINY_PHOTO),
        ("face", None),
    ]
    for m, ph in trials:
        body = {
            "client_punch_id": str(uuid.uuid4()),
            "employee_id": emp["id"],
            "device_time": dt,
            "method": m,
        }
        if ph is not None:
            body["photo_base64"] = ph
        s, resp = call("POST", "/punches", body, tok=token,
                       extra={"X-Device-Key": keys[sid]})
        print(f"  method='{m}': {s}" + ("" if s in (200, 201) else f" {str(resp)[:200]}"))
        if s in (200, 201):
            _WORKING = m
            return

probe()
if not _WORKING:
    print("\nNo method accepted."); sys.exit(1)
print(f"\nUsing method='{_WORKING}'\n")

# seed punches
today = date.today()
dates = [today - timedelta(days=i) for i in range(1, 6)]
NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def punch(emp_id, sid, dt_iso):
    cid = uuid.uuid5(NS, f"{emp_id}-{dt_iso}")
    body = {
        "client_punch_id": str(cid),
        "employee_id": emp_id,
        "device_time": dt_iso,
        "method": _WORKING,
    }
    return call("POST", "/punches", body, tok=token,
                extra={"X-Device-Key": keys[sid]})[0]


total = fails = 0
for i, e in enumerate(emps):
    sid = e.get("site_id")
    if not sid or sid not in keys:
        print(f"- {e['employee_code']}: no device (skip)")
        continue
    for d in dates:
        ds = d.isoformat()
        in_t, out_t = f"{ds}T08:00:00+02:00", f"{ds}T17:00:00+02:00"
        if d == dates[0]:
            if i == 0: out_t = None
            elif i == 1: in_t = None
            elif i == 2: in_t = f"{ds}T10:30:00+02:00"
            elif i == 3: out_t = f"{ds}T20:00:00+02:00"
        if in_t:
            s = punch(e["id"], sid, in_t); total += 1
            if s not in (200, 201): fails += 1; print(f"  ✗ {e['employee_code']} {ds} IN {s}")
        if out_t:
            s = punch(e["id"], sid, out_t); total += 1
            if s not in (200, 201): fails += 1; print(f"  ✗ {e['employee_code']} {ds} OUT {s}")
    print(f"+ {e['employee_code']} {e['first_name']} {e['last_name']}")

print(f"\nDone. {total} punches, {fails} failed.")