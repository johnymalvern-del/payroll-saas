"""Fix test_intelligence_decision_records.py: unique usernames + _admin helper."""
from pathlib import Path

P = Path(__file__).resolve().parent.parent / "backend" / "tests" / "test_intelligence_decision_records.py"
s = P.read_text(encoding="utf-8")

# 1. Replace _mk_user with unique-username default
old_mk = '''def _mk_user(session, username="admin", role="payroll_admin") -> User:
    u = User(
        id=uuid.uuid4(), username=username,
        password_hash=hash_password("x"),
        role=role, is_active=True, must_change_password=False,
        failed_attempts=0, row_version=1,
    )
    session.add(u)
    session.flush()
    return u
'''
new_mk = '''def _mk_user(session, username: str | None = None, role="payroll_admin") -> User:
    if username is None:
        username = f"test-{role}-{uuid.uuid4().hex[:6]}"
    u = User(
        id=uuid.uuid4(), username=username,
        password_hash=hash_password("x"),
        role=role, is_active=True, must_change_password=False,
        failed_attempts=0, row_version=1,
    )
    session.add(u)
    session.flush()
    return u


def _admin(session) -> User:
    from sqlalchemy import select as _sel
    u = session.scalar(_sel(User).where(User.username == "admin"))
    assert u is not None, "auto-provisioned admin missing from tenant"
    return u
'''
if old_mk not in s:
    raise SystemExit("FATAL: _mk_user block not matched")
s = s.replace(old_mk, new_mk, 1)

# 2. In test_list_and_detail_via_http, use _admin instead of _mk_user
old_http = '''def test_list_and_detail_via_http(client, api_tenant, db):
    emp = _mk_emp(db)
    user = _mk_user(db, username="admin", role="payroll_admin")
    db.commit()
'''
new_http = '''def test_list_and_detail_via_http(client, api_tenant, db):
    emp = _mk_emp(db)
    user = _admin(db)
    db.commit()
'''
if old_http not in s:
    raise SystemExit("FATAL: test_list_and_detail_via_http block not matched")
s = s.replace(old_http, new_http, 1)

# 3. test_list_requires_permission — the unused _mk_user is fine with unique username,
#    but tidy: remove it since the test uses unauth path
old_perm = '''def test_list_requires_permission(client, api_tenant, db):
    # employee user (no INTELLIGENCE_VIEW)
    emp = _mk_emp(db)
    u = _mk_user(db, username="emp1", role="employee")
    db.commit()
    # NOTE: cannot login without password hash matching, so use direct 401/403
    # via unauth request
    r = client.get(
        "/api/v1/intelligence/decisions",
        headers={"X-Tenant-Slug": api_tenant.slug},
    )
    assert r.status_code == 401
'''
new_perm = '''def test_list_requires_permission(client, api_tenant, db):
    # no auth token at all -> 401 (unauth, tenant resolved)
    r = client.get(
        "/api/v1/intelligence/decisions",
        headers={"X-Tenant-Slug": api_tenant.slug},
    )
    assert r.status_code == 401
'''
if old_perm in s:
    s = s.replace(old_perm, new_perm, 1)
    print("tightened test_list_requires_permission")
else:
    print("WARN: test_list_requires_permission block not matched — left as-is")

P.write_text(s, encoding="utf-8")
print("patched test_intelligence_decision_records.py")