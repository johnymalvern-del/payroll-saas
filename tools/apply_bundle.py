"""tools/apply_bundle.py - apply a bundle of complete file writes.

Modes:
  default (backend)   ast.parse every .py, import app.main, collect-only + pytest
                      on touched test files and importers of changed sources.
  --frontend          node/npm/npx resolved via shutil.which, launched through
                      cmd.exe /c on Windows (.cmd/.bat); version gate; npm
                      install on package.json change; npx tsc --noEmit on TS
                      change; npx vitest run on touched test files; npm run
                      build only with --build.

Both modes:
  refuse malformed bundles; back up overwritten files; write UTF-8 without BOM;
  full output to bundles/last_run.log; on failure print first error line per
  failure AND the last 15 lines of the log; --commit "<msg>" with repeatable
  --also <path> to include extra files in the commit; --rollback <timestamp>;
  gitignored-safe staging; --push; --record-full-suite-pass.

Bundle format:
    === FILE: <path> ===
    <content>
    === END FILE: <path> ===
"""
from __future__ import annotations

import argparse
import ast
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
BACKUP_ROOT = REPO / ".bundle_backup"
FULL_SUITE_MARKER = REPO / ".last_full_suite_ok"
FRONTEND_DIR = REPO / "frontend"
LOG_FILE = REPO / "bundles" / "last_run.log"

FILE_RE = re.compile(r"^=== FILE: (.+?) ===\s*$")
END_RE = re.compile(r"^=== END FILE: (.+?) ===\s*$")

_MAX_DEPENDENT_TESTS = 20
_LOG_TAIL_LINES = 15


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

def _truncate_log() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("", encoding="utf-8")


def log_line(text: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")


def print_log_tail(n: int = _LOG_TAIL_LINES) -> None:
    if not LOG_FILE.exists():
        return
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    tail = lines[-n:] if len(lines) > n else lines
    if not tail:
        return
    try:
        rel = LOG_FILE.relative_to(REPO)
    except ValueError:
        rel = LOG_FILE
    print(f"\n--- last {len(tail)} lines of {rel} ---")
    for line in tail:
        print(line)


# ---------------------------------------------------------------------------
# External program resolution (Windows-safe for .cmd / .bat)
# ---------------------------------------------------------------------------

def resolve_launcher(name: str) -> list[str]:
    """Return argv prefix that launches `name` on this OS.

    On Windows, npm/npx/node-gyp shims are .cmd files. subprocess cannot run
    them via CreateProcess directly, so route them through cmd.exe /c. The
    path is emitted as a list element and Python's list2cmdline quotes it when
    it contains spaces; cmd.exe /c preserves those quotes when the string
    names an executable (see cmd /? for the quote rules).
    """
    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(f"{name} not found on PATH")
    if os.name == "nt" and path.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", path]
    return [path]


# ---------------------------------------------------------------------------
# Command runner (never raises; always returns CompletedProcess; logs)
# ---------------------------------------------------------------------------

def run_cmd(args: list, cwd: pathlib.Path, timeout: int = 1800) -> subprocess.CompletedProcess:
    try:
        r = subprocess.run(
            args, cwd=str(cwd), capture_output=True, text=True, timeout=timeout
        )
        log_line(f"$ {' '.join(str(a) for a in args)} (cwd={cwd})")
        if r.stdout:
            log_line("stdout:")
            log_line(r.stdout)
        if r.stderr:
            log_line("stderr:")
            log_line(r.stderr)
        log_line(f"exit={r.returncode}")
        return r
    except FileNotFoundError as e:
        msg = f"executable not found: {e}"
        log_line(f"$ {' '.join(str(a) for a in args)} -> {msg}")
        return subprocess.CompletedProcess(args, returncode=127, stdout="", stderr=msg)
    except OSError as e:
        msg = f"OSError launching command: {e}"
        log_line(f"$ {' '.join(str(a) for a in args)} -> {msg}")
        return subprocess.CompletedProcess(args, returncode=126, stdout="", stderr=msg)
    except subprocess.TimeoutExpired as e:
        msg = f"timeout after {e.timeout}s"
        log_line(f"$ {' '.join(str(a) for a in args)} -> {msg}")
        return subprocess.CompletedProcess(args, returncode=124, stdout="", stderr=msg)


# ---------------------------------------------------------------------------
# Bundle parse / write / rollback
# ---------------------------------------------------------------------------

def parse_bundle(path: pathlib.Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines(keepends=True)
    files: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        m = FILE_RE.match(lines[i].rstrip("\r\n"))
        if not m:
            i += 1
            continue
        rel = m.group(1).strip()
        i += 1
        buf: list[str] = []
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


def write_files(files: list[tuple[str, str]], ts: str) -> list[str]:
    backup_dir = BACKUP_ROOT / ts
    backup_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"created": [], "written": [], "timestamp": ts}
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
    (backup_dir / "_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest["written"] + manifest["created"]


def rollback(ts: str) -> list[str]:
    backup_dir = BACKUP_ROOT / ts
    if not backup_dir.exists():
        raise ValueError(f"no backup at {backup_dir}")
    restored: list[str] = []
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


# ---------------------------------------------------------------------------
# Backend gates
# ---------------------------------------------------------------------------

def ast_check(files: list[str]) -> dict[str, tuple[bool, str]]:
    out: dict[str, tuple[bool, str]] = {}
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


def import_check() -> tuple[bool, str]:
    backend = REPO / "backend"
    r = run_cmd([sys.executable, "-c", "from app.main import app; print('ok')"], backend, timeout=120)
    return (r.returncode == 0, (r.stdout + r.stderr).strip())


def collect_check(test_files: list[str]) -> dict[str, tuple[bool, str]]:
    out: dict[str, tuple[bool, str]] = {}
    backend = REPO / "backend"
    for rel in test_files:
        if not rel.startswith("backend/tests/test_") or not rel.endswith(".py"):
            continue
        test_rel = rel[len("backend/"):]
        r = run_cmd([sys.executable, "-m", "pytest", test_rel, "--collect-only", "-q"], backend, timeout=180)
        out[rel] = (r.returncode == 0, (r.stdout + r.stderr).strip())
    return out


def pytest_check(test_files: list[str], fast: bool) -> dict[str, tuple[bool, str]]:
    out: dict[str, tuple[bool, str]] = {}
    backend = REPO / "backend"
    extra = ["-m", "not slow"] if fast else []
    for rel in test_files:
        if not rel.startswith("backend/tests/test_") or not rel.endswith(".py"):
            continue
        test_rel = rel[len("backend/"):]
        r = run_cmd([sys.executable, "-m", "pytest", test_rel, "-q", "--no-header", *extra], backend, timeout=1800)
        out[rel] = (r.returncode == 0, (r.stdout + r.stderr).strip())
    return out


def find_dependent_tests(written: list[str]) -> list[str]:
    source_changed = [f for f in written if f.endswith(".py") and f.startswith("backend/app/")]
    if not source_changed:
        return []
    modules = []
    for f in source_changed:
        rel = f[len("backend/"):]
        modules.append(rel[:-3].replace("/", ".").replace("\\", "."))
    tests_dir = REPO / "backend" / "tests"
    if not tests_dir.is_dir():
        return []
    hits: list[str] = []
    for t in tests_dir.rglob("test_*.py"):
        try:
            txt = t.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in modules:
            if f"from {m}" in txt or f"import {m}" in txt:
                hits.append(str(t.relative_to(REPO)))
                break
    hits = sorted(set(hits))
    if len(hits) > _MAX_DEPENDENT_TESTS:
        print(f"WARN: {len(hits)} tests import changed sources; capped at {_MAX_DEPENDENT_TESTS}")
        hits = hits[:_MAX_DEPENDENT_TESTS]
    return hits


# ---------------------------------------------------------------------------
# Frontend gates
# ---------------------------------------------------------------------------

def node_version_check() -> tuple[bool, str]:
    try:
        node = resolve_launcher("node")
        npm = resolve_launcher("npm")
    except FileNotFoundError as e:
        return False, str(e)
    r = run_cmd(node + ["--version"], REPO, timeout=30)
    if r.returncode != 0:
        return False, f"node --version failed (exit {r.returncode}): {r.stderr.strip()[:200]}"
    m = re.match(r"v(\d+)\.", r.stdout.strip())
    if not m:
        return False, f"cannot parse node version: {r.stdout.strip()!r}"
    major = int(m.group(1))
    if major < 20:
        return False, f"node major {major} < 20 (need Node 20 LTS or newer)"
    r2 = run_cmd(npm + ["--version"], REPO, timeout=30)
    if r2.returncode != 0:
        return False, f"npm --version failed (exit {r2.returncode}): {r2.stderr.strip()[:200]}"
    return True, f"node v{major}, npm {r2.stdout.strip()}"


def frontend_npm_install(written: list[str]) -> tuple[bool, str]:
    pkg = FRONTEND_DIR / "package.json"
    if not pkg.exists():
        return True, "skip: no frontend/package.json"
    if "frontend/package.json" not in written:
        return True, "skip: package.json unchanged"
    try:
        npm = resolve_launcher("npm")
    except FileNotFoundError as e:
        return False, str(e)
    r = run_cmd(npm + ["install"], FRONTEND_DIR, timeout=900)
    if r.returncode != 0:
        return False, "npm install FAILED"
    return True, "npm install ok"


def frontend_tsc(written: list[str]) -> tuple[bool, str]:
    if not FRONTEND_DIR.exists():
        return True, "skip: no frontend dir"
    ts_changed = any(
        (f.endswith(".ts") or f.endswith(".tsx")) and f.startswith("frontend/")
        for f in written
    )
    if not ts_changed:
        return True, "skip: no TS change"
    if not (FRONTEND_DIR / "node_modules").exists():
        return True, "skip: node_modules missing (run npm install first)"
    try:
        npx = resolve_launcher("npx")
    except FileNotFoundError as e:
        return False, str(e)
    r = run_cmd(npx + ["tsc", "--noEmit"], FRONTEND_DIR, timeout=600)
    if r.returncode != 0:
        return False, "tsc FAILED"
    return True, "tsc ok"


def frontend_vitest(written: list[str]) -> tuple[bool, str, dict[str, tuple[bool, str]]]:
    if not FRONTEND_DIR.exists():
        return True, "skip: no frontend dir", {}
    test_files = [
        f for f in written
        if f.startswith("frontend/") and (".test." in f or ".spec." in f)
    ]
    if not test_files:
        return True, "skip: no test files changed", {}
    if not (FRONTEND_DIR / "node_modules").exists():
        return True, "skip: node_modules missing", {}
    try:
        npx = resolve_launcher("npx")
    except FileNotFoundError as e:
        return False, str(e), {}
    results: dict[str, tuple[bool, str]] = {}
    for f in test_files:
        rel = f[len("frontend/"):]
        r = run_cmd(npx + ["vitest", "run", rel], FRONTEND_DIR, timeout=300)
        results[f] = (r.returncode == 0, (r.stdout + r.stderr).strip())
    overall = all(ok for ok, _ in results.values())
    return overall, f"vitest on {len(test_files)} file(s)", results


def frontend_build(enabled: bool) -> tuple[bool, str]:
    if not enabled:
        return True, "skip: --build not set"
    if not (FRONTEND_DIR / "package.json").exists():
        return True, "skip: no frontend/package.json"
    if not (FRONTEND_DIR / "node_modules").exists():
        return True, "skip: node_modules missing"
    try:
        npm = resolve_launcher("npm")
    except FileNotFoundError as e:
        return False, str(e)
    r = run_cmd(npm + ["run", "build"], FRONTEND_DIR, timeout=900)
    if r.returncode != 0:
        return False, "npm run build FAILED"
    return True, "build ok"


# ---------------------------------------------------------------------------
# Table printing
# ---------------------------------------------------------------------------

def first_fail(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if (
            "FAILED" in s or s.startswith("ERROR") or "AssertionError" in s
            or "SyntaxError" in s or "error TS" in s
        ):
            return s
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return lines[-1] if lines else ""


def print_table_backend(written, ast_res, imp_res, collect_res, pytest_res) -> bool:
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


def print_table_frontend(written, ast_res, node_res, npm_res, tsc_res, vitest_res, build_res) -> bool:
    _, _, vitest_map = vitest_res
    print(f"{'FILE':<55} {'WRITTEN':<8} {'PARSE':<6} {'TESTS':<10}")
    print("-" * 82)
    ok = True
    for rel in written:
        parse_ok = ast_res.get(rel, (True, ""))[0]
        parse_s = "ok" if parse_ok else "FAIL"
        if not parse_ok:
            ok = False
        test_s = "-"
        if rel in vitest_map:
            t_ok, _ = vitest_map[rel]
            test_s = "pass" if t_ok else "FAIL"
            if not t_ok:
                ok = False
        print(f"{rel:<55} {'yes':<8} {parse_s:<6} {test_s:<10}")
    for label, res in [
        ("NODE", node_res), ("NPM", npm_res),
        ("TSC", tsc_res), ("VITEST", vitest_res), ("BUILD", build_res),
    ]:
        r_ok = res[0]
        r_msg = res[1] if len(res) > 1 else ""
        if not r_ok:
            ok = False
            print(f"\n{label} FAIL: {r_msg}")
    return ok


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

def do_commit(files: list[str], message: str) -> bool:
    if not files:
        print("commit: no files")
        return True
    try:
        git = resolve_launcher("git")
    except FileNotFoundError as e:
        print(f"git not found: {e}")
        return False
    tracked: list[str] = []
    skipped: list[str] = []
    for f in files:
        r = run_cmd(git + ["check-ignore", "-q", f], REPO, timeout=30)
        if r.returncode == 0:
            skipped.append(f)
            continue
        tracked.append(f)
    if skipped:
        print(f"commit: skipping gitignored: {skipped}")
    if not tracked:
        print("commit: no tracked files")
        return True
    r = run_cmd(git + ["add", *tracked], REPO, timeout=120)
    if r.returncode != 0:
        print(f"git add failed: {r.stderr.strip()}")
        return False
    r = run_cmd(git + ["commit", "-m", message], REPO, timeout=120)
    if r.returncode != 0:
        print(f"git commit failed: {r.stderr.strip() or r.stdout.strip()}")
        return False
    print(f"committed: {message}")
    return True


def do_push() -> bool:
    try:
        git = resolve_launcher("git")
    except FileNotFoundError as e:
        print(f"git not found: {e}")
        return False
    r = run_cmd(git + ["status", "--porcelain"], REPO, timeout=60)
    if r.returncode != 0:
        print(f"git status failed: {r.stderr.strip()}")
        return False
    if r.stdout.strip():
        print("push refused: working tree not clean")
        print(r.stdout.strip())
        return False
    if not FULL_SUITE_MARKER.exists():
        print("push refused: no recorded full-suite pass")
        print("run full suite, then: python tools\\apply_bundle.py --record-full-suite-pass")
        return False
    r = run_cmd(git + ["push", "origin", "main"], REPO, timeout=300)
    if r.returncode != 0:
        print(f"push failed: {r.stderr.strip()}")
        return False
    print("pushed to origin/main")
    return True


def record_full_suite_pass() -> None:
    FULL_SUITE_MARKER.write_text(datetime.datetime.now().isoformat(), encoding="utf-8")
    print(f"recorded full-suite pass at {FULL_SUITE_MARKER}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Apply a bundle of complete file writes.")
    p.add_argument("bundle", nargs="?")
    p.add_argument("--frontend", action="store_true")
    p.add_argument("--build", action="store_true")
    p.add_argument("--fast", action="store_true")
    p.add_argument(
        "--also",
        action="append",
        default=[],
        metavar="PATH",
        help="Additional path to include in --commit (repeatable). "
             "Useful for including tools/apply_bundle.py itself.",
    )
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
        ok = do_push()
        if not ok:
            print_log_tail()
            return 1
        return 0
    if not args.bundle:
        print("error: bundle path required (or --push/--rollback/--record-full-suite-pass)")
        return 1

    _truncate_log()

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
        print(f"STOP writing: {e}")
        return 1
    print(f"wrote {len(written)} files; backup at .bundle_backup/{ts}")
    log_line(f"=== bundle {bundle_path.name} at {ts} ===")
    log_line(f"wrote: {written}")

    ast_res = ast_check(written)

    if args.frontend:
        node_ok, node_msg = node_version_check()
        if not node_ok:
            print(f"\nSTOP: {node_msg}")
            print_log_tail()
            return 1
        npm_res = frontend_npm_install(written)
        tsc_res = frontend_tsc(written) if npm_res[0] else (False, "skipped: npm install failed")
        vitest_res = (
            frontend_vitest(written)
            if (npm_res[0] and tsc_res[0])
            else (False, "skipped: earlier gate failed", {})
        )
        build_res = (
            frontend_build(args.build)
            if (npm_res[0] and tsc_res[0] and vitest_res[0])
            else (True, "skip: earlier gate failed")
        )
        ok = print_table_frontend(
            written, ast_res, (node_ok, node_msg), npm_res, tsc_res, vitest_res, build_res
        )
    else:
        imp_res = import_check()
        direct = [f for f in written if f.startswith("backend/tests/test_")]
        dep = find_dependent_tests(written)
        all_tests = sorted(set(direct) | set(dep))
        extra_dep = set(dep) - set(direct)
        if extra_dep:
            print(f"running {len(extra_dep)} dependent test files")
        collect_res = collect_check(all_tests)
        pytest_res = pytest_check(all_tests, fast=args.fast)
        ok = print_table_backend(written, ast_res, imp_res, collect_res, pytest_res)

    if not ok:
        print(f"\nFAILED. Rollback: python tools/apply_bundle.py --rollback {ts}")
        print_log_tail()
        return 1

    if args.commit:
        to_commit = list(dict.fromkeys(list(written) + list(args.also)))
        if not do_commit(to_commit, args.commit):
            print_log_tail()
            return 1

    print("\nOK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())