"""Milestone 2 closeout probe. Read-only.

Inspects:
- Which investigation scripts are committed vs untracked
- What is in backend/var/storage/punches/
- Whether .gitignore already excludes runtime storage
- The current ClockInPage + clockIn.ts + ClockInPage.test.tsx shapes
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "frontend" / "src"
BE = ROOT / "backend"


def run(cmd, cwd=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=cwd or ROOT, shell=True, timeout=20)
        return (r.stdout or r.stderr).strip()
    except Exception as e:
        return f"ERR: {e}"


def dump(path, first=None, last=None):
    p = Path(path)
    if not p.exists():
        print(f"--- {path} NOT FOUND ---")
        return
    lines = p.read_text(encoding="utf-8").split("\n")
    if first is None:
        first = 1
    if last is None:
        last = len(lines)
    print(f"--- {path} lines {first}–{last} of {len(lines)} ---")
    for i in range(first - 1, min(last, len(lines))):
        print(f"{i+1:4}: {lines[i]}")
    print()


print("=" * 60)
print("SECTION 1 — which milestone2 scripts are tracked in git?")
print("=" * 60)
tracked = run("git ls-files tools/milestone2_*.py tools/milestone1_*.py tools/p1b_*.py tools/p1a_*.py tools/milestone*.py")
print(tracked or "(none tracked)")
print()
untracked = run("git status --porcelain tools/")
print("untracked/modified under tools/:")
print(untracked or "(clean)")

print("=" * 60)
print("SECTION 2 — backend/var/storage/ contents + tracked files")
print("=" * 60)
if (BE / "var").exists():
    for p in sorted((BE / "var").rglob("*")):
        if p.is_file():
            rel = p.relative_to(ROOT)
            size = p.stat().st_size
            print(f"  {rel}  ({size} bytes)")
    tracked_storage = run("git ls-files backend/var")
    print()
    print("Tracked files under backend/var/:")
    print(tracked_storage or "(none tracked)")
else:
    print("  backend/var/ does not exist")

print("=" * 60)
print("SECTION 3 — .gitignore state")
print("=" * 60)
for candidate in (".gitignore", "backend/.gitignore", "frontend/.gitignore"):
    p = ROOT / candidate
    if p.exists():
        content = p.read_text(encoding="utf-8")
        print(f"--- {candidate} ---")
        print(content)
        print()
    else:
        print(f"--- {candidate} NOT FOUND ---")

print("=" * 60)
print("SECTION 4 — frontend clockIn.ts PunchOut type")
print("=" * 60)
dump(FE / "api" / "clockIn.ts")

print("=" * 60)
print("SECTION 5 — ClockInPage.tsx current success/error handling")
print("=" * 60)
# Show the whole file — we need to see the phase state machine
dump(FE / "pages" / "ClockInPage.tsx")

print("=" * 60)
print("SECTION 6 — strings.ts clockIn block")
print("=" * 60)
st = FE / "lib" / "strings.ts"
if st.exists():
    lines = st.read_text(encoding="utf-8").split("\n")
    start = None
    for i, ln in enumerate(lines):
        if "clockIn:" in ln:
            start = i
            break
    if start is not None:
        end = start + 1
        while end < len(lines) and not (
            lines[end].strip().startswith("},")
        ):
            end += 1
        end = min(end + 1, len(lines))
        for j in range(start, end):
            print(f"{j+1:4}: {lines[j]}")
    else:
        print("clockIn block not found")

print("\n" + "=" * 60)
print("SECTION 7 — ClockInPage.test.tsx head (mock + first tests)")
print("=" * 60)
dump(FE / "pages" / "ClockInPage.test.tsx", first=1, last=60)