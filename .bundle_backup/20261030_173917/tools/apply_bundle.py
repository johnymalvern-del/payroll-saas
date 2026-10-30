"""tools/apply_bundle.py - apply a bundle of complete file writes.

Bundle format:
    === FILE: backend/app/x.py ===
    <complete file content>
    === END FILE: backend/app/x.py ===

Commands:
    python tools\apply_bundle.py bundles\001.txt --commit "msg"
    python tools\apply_bundle.py bundles\001.txt --fast --commit "msg"
    python tools\apply_bundle.py --rollback <timestamp>
    python tools\apply_bundle.py --record-full-suite-pass
    python tools\apply_bundle.py --push
"""
from __future__ import annotations

import argparse
import ast
import datetime
import json
import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
BACKUP_ROOT = REPO / ".bundle_backup"
FULL_SUITE_MARKER = REPO / ".last_full_suite_ok"

FILE_RE = re.compile(r"^=== FILE: (.+?) ===\s*$")
END_RE = re.compile(r"^=== END FILE: (.+?) ===\s*$")


def parse_bundle(path: pathlib.Path):
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines(keepends=True)
    files = []
    i = 0
    while i < len(lines):
        m = FILE_RE.match(lines[i].rstrip("\r\n"))
        if not m:
            i += 1
            continue
        rel = m.group(1).strip()
        i += 1
        buf = []
        ended = False
        while i < len(lines):
            em = END_RE.match(lines[i].rstrip("\r\n"))
            if em and em.group(1).strip() == rel:
                ended = True
                i += 1
                break
            buf.append(lines[i])
            i += 1
        if not ended:
            raise ValueError(f"file {rel}: missing END FILE marker")
        files.append((rel, "".join(buf)))
    if not files:
        raise ValueError(f"no files parsed from bundle {path}")
    for rel, _ in files:
        target = (REPO / rel).resolve()
        try:
            target.relative_to(REPO.resolve())
        except ValueError:
            raise ValueError(f"path escapes repository: {rel}")
    return files


def write_files(files, ts):
    backup_dir = BACKUP_ROOT / ts
    backup_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"created": [], "written": [], "timestamp": ts}
    for rel, content in files:
        target = REPO / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            backup_target = backup_dir / rel
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_target)
            manifest["written"].append(rel)
        else:
            manifest["created"].append(rel)
        target.write_text(content, encoding="utf-8", newline="")
    (backup_dir / "_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest["written"] + manifest["created"]


def rollback(ts):
    backup_dir = BACKUP_ROOT / ts
    if not backup_dir.exists():
        raise ValueError(f"no backup at {backup_dir}")
    restored = []
    manifest_path = backup_dir / "_MANIFEST.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for rel in manifest.get("created", []):
            target = REPO / rel
            if target.exists():
                target.unlink()
    for p in backup_dir.rglob("*"):
        if p.is_file() and p.name != "_MANIFEST.json":
            rel = p.relative_to(backup_dir)
            target = REPO / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            restored.append(str(rel))
    return restored


def run_cmd(args, cwd, timeout=1800):
    try:
        return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(args, returncode=124, stdout="", stderr=f"timeout {e.timeout}s")


def ast_check(files):
    out = {}
    for rel in files:
        if not rel.endswith(".py"):
            out[rel] = (True, "")
            continue
        try:
            ast.parse((REPO / rel).read_text(encoding="utf-8"))
            out[rel] = (True, "")
        except SyntaxError as e:
            out[rel] = (False, f"{e.msg} (line {e.lineno})")
    return out


def import_check():
    backend = REPO / "backend"
    r = run_cmd([sys.executable, "-c", "from app.main import app; print('ok')"], backend, timeout=120)
    return (r.returncode == 0, (r.stdout + r.stderr).strip())


def collect_check(test_files):
    out = {}
    backend = REPO / "backend"
    for rel in test_files:
        if not rel.startswith("backend/tests/test_") or not rel.endswith(".py"):
            continue
        test_rel = rel[len("backend/"):]
        r = run_cmd([sys.executable, "-m", "pytest", test_rel, "--collect-only", "-q"], backend, timeout=180)
        out[rel] = (r.returncode == 0, (r.stdout + r.stderr).strip())
    return out


def pytest_check(test_files, fast):
    out = {}
    backend = REPO / "backend"
    extra = ["-m", "not slow"] if fast else []
    for rel in test_files:
        if not rel.startswith("backend/tests/test_") or not rel.endswith(".py"):
            continue
        test_rel = rel[len("backend/"):]
        r = run_cmd([sys.executable, "-m", "pytest", test_rel, "-q", "--no-header", *extra], backend, timeout=1800)
        out[rel] = (r.returncode == 0, (r.stdout + r.stderr).strip())
    return out


def first_fail(text):
    for line in text.splitlines():
        s = line.strip()
        if "FAILED" in s or s.startswith("ERROR") or "AssertionError" in s or "SyntaxError" in s:
            return s
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return lines[-1] if lines else ""


def print_table(written, ast_res, imp_res, collect_res, pytest_res):
    print(f"{'FILE':<55} {'WRITTEN':<8} {'PARSE':<6} {'TESTS':<10}")
    print("-" * 82)
    ok = True
    for rel in written:
        parse_ok = ast_res.get(rel, (True, ""))[0]
        parse_s = "ok" if parse_ok else "FAIL"
        if not parse_ok:
            ok = False
        test_s = "-"
        if rel in pytest_res:
            t_ok, t_out = pytest_res[rel]
            if t_ok:
                m = re.search(r"(\d+) passed", t_out)
                test_s = f"{m.group(1)} pass" if m else "pass"
            else:
                test_s = "FAIL"
                ok = False
        print(f"{rel:<55} {'yes':<8} {parse_s:<6} {test_s:<10}")
    if not imp_res[0]:
        ok = False
        print(f"\nIMPORT FAIL: {first_fail(imp_res[1])}")
    for rel, (c_ok, c_out) in collect_res.items():
        if not c_ok:
            ok = False
            print(f"\nCOLLECT FAIL {rel}: {first_fail(c_out)}")
    for rel, (p_ok, p_out) in pytest_res.items():
        if not p_ok:
            print(f"\nPYTEST FAIL {rel}: {first_fail(p_out)}")
    return ok


def do_commit(files, message):
    if not files:
        print("commit: no files")
        return True
    r = run_cmd(["git", "add", *files], REPO, timeout=120)
    if r.returncode != 0:
        print(f"git add failed: {r.stderr.strip()}")
        return False
    r = run_cmd(["git", "commit", "-m", message], REPO, timeout=120)
    if r.returncode != 0:
        print(f"git commit failed: {r.stderr.strip() or r.stdout.strip()}")
        return False
    print(f"committed: {message}")
    return True


def do_push():
    r = run_cmd(["git", "status", "--porcelain"], REPO, timeout=60)
    if r.returncode != 0:
        print(f"git status failed: {r.stderr.strip()}")
        return False
    if r.stdout.strip():
        print("push refused: working tree not clean")
        print(r.stdout.strip())
        return False
    if not FULL_SUITE_MARKER.exists():
        print("push refused: no recorded full-suite pass")
        print("run the full suite, then: python tools\\apply_bundle.py --record-full-suite-pass")
        return False
    r = run_cmd(["git", "push", "origin", "main"], REPO, timeout=300)
    if r.returncode != 0:
        print(f"push failed: {r.stderr.strip()}")
        return False
    print("pushed to origin/main")
    return True


def record_full_suite_pass():
    FULL_SUITE_MARKER.write_text(datetime.datetime.now().isoformat(), encoding="utf-8")
    print(f"recorded full-suite pass at {FULL_SUITE_MARKER}")


def main():
    p = argparse.ArgumentParser(description="Apply a bundle of complete file writes.")
    p.add_argument("bundle", nargs="?")
    p.add_argument("--fast", action="store_true")
    p.add_argument("--commit", metavar="MSG")
    p.add_argument("--push", action="store_true")
    p.add_argument("--rollback", metavar="TS")
    p.add_argument("--record-full-suite-pass", action="store_true")
    args = p.parse_args()

    if args.record_full_suite_pass:
        record_full_suite_pass()
        return 0
    if args.rollback:
        try:
            restored = rollback(args.rollback)
        except ValueError as e:
            print(f"STOP: {e}")
            return 1
        print(f"restored {len(restored)} files from backup {args.rollback}")
        for r in restored:
            print(f"  {r}")
        return 0
    if args.push:
        return 0 if do_push() else 1
    if not args.bundle:
        print("error: bundle path required (or --push/--rollback/--record-full-suite-pass)")
        return 1

    bundle_path = pathlib.Path(args.bundle)
    if not bundle_path.exists():
        print(f"STOP: bundle {bundle_path} not found")
        return 1
    try:
        files = parse_bundle(bundle_path)
    except ValueError as e:
        print(f"STOP: {e} (bundle rejected; nothing written)")
        return 1

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        written = write_files(files, ts)
    except Exception as e:
        print(f"STOP writing files: {e}")
        return 1
    print(f"wrote {len(written)} files; backup at .bundle_backup/{ts}")

    ast_res = ast_check(written)
    imp_res = import_check()
    test_files = [f for f in written if f.startswith("backend/tests/test_")]
    collect_res = collect_check(test_files)
    pytest_res = pytest_check(test_files, fast=args.fast)

    ok = print_table(written, ast_res, imp_res, collect_res, pytest_res)

    if not ok:
        print(f"\nFAILED. Rollback: python tools/apply_bundle.py --rollback {ts}")
        return 1
    if args.commit:
        if not do_commit(written, args.commit):
            return 1
    print("\nOK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
# END OF FILE