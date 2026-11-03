"""L2d fix7:
1. _apply_chain: set request.status='submitted' when steps are created.
   (Only the auto-approve branch set status; the pending-chain branch left
   it at 'draft', so submit returned status='draft' even after reserving.)
2. Speed fix: add conftest session-scoped tenant-seeded fixture +
   function-scoped Session with rollback-per-test; rewrite per-file
   `session` fixtures as thin stubs delegating to conftest.
3. Diagnostics: dump final _apply_chain, the per-file session stubs, and
   print each test file's collected test IDs (for the 28-line table).
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTER = ROOT / "backend" / "app" / "api" / "v1" / "leave_requests.py"
CONF = ROOT / "backend" / "tests" / "conftest.py"
T1 = ROOT / "backend" / "tests" / "test_leave_requests.py"
T2 = ROOT / "backend" / "tests" / "test_leave_approval.py"

# --- 1. _apply_chain status fix ---
src = ROUTER.read_text(encoding="utf-8")
pattern = re.compile(
    r"(def _apply_chain\(.*?for idx, role in enumerate\(chain, start=1\):"
    r".*?db\.add\(step\)\n)"
    r"    db\.flush\(\)",
    re.S,
)
m = pattern.search(src)
if not m:
    raise SystemExit("FATAL: _apply_chain tail pattern not found")
if "request.status = \"submitted\"\n    db.flush()" in src:
    print("_apply_chain already patched")
else:
    new_block = m.group(1) + "    request.status = \"submitted\"\n    db.flush()"
    src = src[:m.start()] + new_block + src[m.end():]
    ROUTER.write_text(src, encoding="utf-8")
    print("_apply_chain patched: sets status='submitted' when steps created")

# --- 2. Conftest fixtures ---
conf_src = CONF.read_text(encoding="utf-8")
MARKER = "# --- LEAVE_TEST_FAST_FIXTURES ---"
if MARKER not in conf_src:
    addition = '''

# --- LEAVE_TEST_FAST_FIXTURES ---
@pytest.fixture(scope="session")
def _leave_tenant_seeded(tenant_engine_admin):
    """Seed the session-scoped tenant with one admin user; yield engine."""
    from sqlalchemy.orm import Session as _Sess
    try:
        from app.db.tenant.models import User as _U
    except Exception:
        from app.db.tenant.models.user import User as _U
    _s = _Sess(tenant_engine_admin)
    try:
        if _s.query(_U).filter(_U.username == "admin").first() is None:
            _s.add(_U(
                username="admin", password_hash="x",
                role="payroll_admin", is_active=True,
                must_change_password=False, failed_attempts=0,
                row_version=1,
            ))
            _s.commit()
    finally:
        _s.close()
    yield tenant_engine_admin


@pytest.fixture()
def _leave_session_shared(_leave_tenant_seeded):
    """Per-test Session on a transactional connection; rollback on teardown."""
    from sqlalchemy.orm import sessionmaker as _sm
    _conn = _leave_tenant_seeded.connect()
    _tx = _conn.begin()
    _Sess = _sm(bind=_conn)
    _s = _Sess()
    try:
        yield _s
    finally:
        _s.close()
        _tx.rollback()
        _conn.close()
# --- END LEAVE_TEST_FAST_FIXTURES ---
'''
    CONF.write_text(conf_src + addition, encoding="utf-8")
    print("conftest: added _leave_tenant_seeded + _leave_session_shared")
else:
    print("conftest: fixtures already present")

# --- 3. AST-based per-file session replacement ---
def replace_session(path):
    src = path.read_text(encoding="utf-8")
    if "def session(_leave_session_shared):" in src:
        print(f"{path.name}: session already stubbed")
        return
    tree = ast.parse(src)
    lines = src.split("\n")
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "session":
            start = node.lineno - 1
            for dec in node.decorator_list:
                if dec.lineno - 1 < start:
                    start = dec.lineno - 1
            end = node.end_lineno
            stub = [
                "@pytest.fixture()",
                "def session(_leave_session_shared):",
                "    return _leave_session_shared",
            ]
            new_lines = lines[:start] + stub + lines[end:]
            path.write_text("\n".join(new_lines), encoding="utf-8")
            print(f"{path.name}: session fixture {end - start} lines -> 3-line stub")
            return
    print(f"{path.name}: WARN session fixture not found (leaving untouched)")

replace_session(T1)
replace_session(T2)

# --- 4. Print final _apply_chain ---
r = ROUTER.read_text(encoding="utf-8")
m2 = re.search(r"def _apply_chain\(.*?(?=\n\ndef |\n\n@|\Z)", r, re.S)
print("=== _apply_chain FINAL ===")
print(m2.group(0) if m2 else "NOT FOUND")

# --- 5. Print the session stubs ---
for p in (T1, T2):
    s = p.read_text(encoding="utf-8")
    m3 = re.search(r"@pytest\.fixture\(\)\ndef session\([^)]*\).*?(?=\n\n|\Z)", s, re.S)
    print(f"=== {p.name} session stub ===")
    print(m3.group(0) if m3 else "NOT FOUND")

# --- 6. Print all test IDs from both files ---
print("=== test_leave_requests.py IDs ===")
s = T1.read_text(encoding="utf-8")
for mm in re.finditer(r"^def (test_[a-z0-9_]+)\(", s, re.M):
    print(f"  {mm.group(1)}")
print("=== test_leave_approval.py IDs ===")
s = T2.read_text(encoding="utf-8")
for mm in re.finditer(r"^def (test_[a-z0-9_]+)\(", s, re.M):
    print(f"  {mm.group(1)}")