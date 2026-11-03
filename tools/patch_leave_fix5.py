"""L2d fix5: undo self-recursion in _commit_or_map.

The prior blanket replace turned `    db.commit()` into `    _commit_or_map(db)`
inside the helper itself. This bundle replaces that one occurrence back to
`        db.commit()` and then AST-checks every function in the file for
self-recursion. Also dumps the `session` fixture from both leave test files
(needed to wire the session-scoped tenant fast path) and, if present, prints
the pytest line from tools/apply_bundle.py.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTER = ROOT / "backend" / "app" / "api" / "v1" / "leave_requests.py"
TEST1 = ROOT / "backend" / "tests" / "test_leave_requests.py"
TEST2 = ROOT / "backend" / "tests" / "test_leave_approval.py"
AB = ROOT / "tools" / "apply_bundle.py"

src = ROUTER.read_text(encoding="utf-8")

# ---- 1. Fix self-recursion inside _commit_or_map ----
broken = (
    "def _commit_or_map(db: Any) -> None:\n"
    "    try:\n"
    "        _commit_or_map(db)\n"
    "    except IntegrityError as exc:"
)
fixed = (
    "def _commit_or_map(db: Any) -> None:\n"
    "    try:\n"
    "        db.commit()\n"
    "    except IntegrityError as exc:"
)
n = src.count(broken)
if n != 1:
    # try alternate: the body may have different indentation
    broken_alt = (
        "def _commit_or_map(db: Any) -> None:\n"
        "    try:\n"
        "        _commit_or_map(db)\n"
    )
    n = src.count(broken_alt)
    if n != 1:
        raise SystemExit(
            f"FATAL: _commit_or_map broken-body signature not found "
            f"(count={n}); refusing to guess"
        )
    # indentation-neutral fix: only replace the inner self-call line
    src = src.replace(
        "        _commit_or_map(db)\n", "        db.commit()\n", 1,
    )
    print("fixed _commit_or_map self-recursion (alt path)")
else:
    src = src.replace(broken, fixed, 1)
    print("fixed _commit_or_map self-recursion")

# ---- 2. AST self-recursion audit across whole file ----
tree = ast.parse(src)
warnings = []
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        fname = node.name
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                f = sub.func
                if isinstance(f, ast.Name) and f.id == fname:
                    warnings.append(
                        f"  line {sub.lineno}: {fname}() calls itself"
                    )
if warnings:
    print("=== SELF-RECURSION IN FILE ===")
    for w in warnings:
        print(w)
else:
    print("=== SELF-RECURSION IN FILE: none ===")

ROUTER.write_text(src, encoding="utf-8")

# ---- 3. Print final text of _commit_or_map and _rebuild_days ----
def dump_fn(name):
    m = re.search(
        rf"def {name}\(.*?(?=\n\ndef |\n\n@|\Z)",
        src, re.S,
    )
    if not m:
        print(f"=== {name} FINAL: NOT FOUND ===")
        return
    print(f"=== {name} FINAL ===")
    print(m.group(0))

dump_fn("_commit_or_map")
dump_fn("_rebuild_days")

# ---- 4. Dump `session` fixture from each leave test file ----
def dump_session_fixture(path):
    if not path.exists():
        print(f"WARN: {path} not found")
        return
    c = path.read_text(encoding="utf-8")
    m = re.search(
        r"(@pytest\.fixture[^\n]*\n)?def session\([^)]*\).*?(?=\n\ndef |\n\n@pytest\.fixture|\Z)",
        c, re.S,
    )
    print(f"=== {path.name} session fixture ===")
    if m:
        print(m.group(0)[:4000])
    else:
        print("SESSION FIXTURE NOT FOUND - first 100 lines:")
        print("\n".join(c.split("\n")[:100]))

dump_session_fixture(TEST1)
dump_session_fixture(TEST2)

# ---- 5. apply_bundle.py pytest line (if present) ----
if AB.exists():
    abc = AB.read_text(encoding="utf-8")
    found = False
    for line in abc.split("\n"):
        s = line.strip()
        if "pytest" in s and not s.startswith("#"):
            print(f"apply_bundle.py: {s}")
            found = True
    if not found:
        print("apply_bundle.py: no pytest line found")
else:
    print("apply_bundle.py: NOT FOUND")