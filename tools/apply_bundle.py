"""
apply_bundle.py - Apply a bundle of complete files, then optionally run frontend checks.

Bundle format:
    === FILE: path/to/file ===
    <content>
    === END FILE: path/to/file ===

Usage:
    python tools\\apply_bundle.py bundles\\fNNN.txt --frontend --commit "msg"

Flags:
    --frontend       Run tsc --noEmit then vitest run (cwd=frontend/). Writes bundles/last_run.log.
    --commit MSG     git add -A && git commit -m MSG (only if frontend checks pass).
    --dry-run        Parse the bundle and print files that would be written; do not write.
    --no-test        Skip vitest (still runs tsc if --frontend).

Damage guard:
    Refuses to write any .py file whose content shows signs of markdown
    damage (rendered-text copy). Exit code 3 on refusal. Signs include:
      * "from future import" - markdown ate the underscores in "__future__".
      * "if name == 'main'" - markdown ate the underscores in "__name__".
      * "Path(file)" - markdown ate the underscores in "__file__".
      * ast.parse fails with IndentationError / TabError - lost indentation.
      * 5+ code lines ending in ":" but zero indented lines - lost indentation.
    Also refuses if the bundle's last non-empty line is not an END FILE marker.
"""
import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

FILE_RE = re.compile(r'^=== FILE: (.+?) ===$')
END_RE = re.compile(r'^=== END FILE: (.+?) ===$')
ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
FILE_LOC_RE = re.compile(r'([\w./\\-]+\.test\.tsx?):(\d+):\d+')
FRONTEND_DIR = 'frontend'

_DAMAGE_PATTERNS = [
    (
        re.compile(r'^from future import\b', re.MULTILINE),
        'line starts with "from future import" (was likely "from __future__ import")',
    ),
    (
        re.compile(r'^\s*if name ==\s*["\']__main__["\']', re.MULTILINE),
        'line starts with "if name == __main__" (was likely "if __name__ == __main__")',
    ),
    (
        re.compile(r'\bPath\(file\)'),
        'contains "Path(file)" (was likely "Path(__file__)")',
    ),
]


def parse_bundle(path):
    files = {}
    current = None
    buf = []
    with open(path, 'r', encoding='utf-8') as f:
        for raw in f:
            line = raw.rstrip('\n').rstrip('\r')
            if line.startswith('\ufeff'):
                line = line.lstrip('\ufeff')
            m = FILE_RE.match(line)
            if m:
                current = m.group(1).strip()
                buf = []
                continue
            m = END_RE.match(line)
            if m:
                end_name = m.group(1).strip()
                if current and end_name == current:
                    files[current] = '\n'.join(buf)
                    current = None
                    buf = []
                continue
            if current is not None:
                buf.append(line)
    return files


def _looks_damaged_py(rel, content):
    for pat, why in _DAMAGE_PATTERNS:
        if pat.search(content):
            return '{}: {}'.format(rel, why)
    try:
        ast.parse(content)
    except IndentationError as e:
        return '{}: IndentationError at line {} - lost indentation'.format(
            rel, e.lineno
        )
    except TabError as e:
        return '{}: TabError at line {} - mixed indentation'.format(rel, e.lineno)
    except SyntaxError:
        pass
    lines = content.splitlines()
    code_colon = 0
    indented = 0
    for L in lines:
        if L and L[0] in ' \t':
            indented += 1
        stripped = L.strip()
        if stripped and not stripped.startswith('#') and L.rstrip().endswith(':'):
            code_colon += 1
    if code_colon >= 5 and indented == 0:
        return '{}: {} code lines end with ":" but no line is indented - lost indentation'.format(
            rel, code_colon
        )
    return None


def _last_non_empty_line(path):
    with open(path, 'r', encoding='utf-8') as f:
        lines = [L.rstrip('\n').rstrip('\r') for L in f]
    for L in reversed(lines):
        if L.strip():
            return L.strip()
    return ''


def _bundle_looks_damaged(path, files):
    last = _last_non_empty_line(path)
    if not END_RE.match(last):
        return (
            'bundle last non-empty line is not an END FILE marker: '
            '{!r}'.format(last[:80])
        )
    for rel, content in files.items():
        if not rel.endswith('.py'):
            continue
        why = _looks_damaged_py(rel, content)
        if why:
            return why
    return None


def write_files(files):
    for rel, content in files.items():
        p = Path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        content = content.lstrip('\ufeff')
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            if content and not content.endswith('\n'):
                content += '\n'
            f.write(content)
        print('wrote {}'.format(rel))


def make_env():
    env = os.environ.copy()
    env['NO_COLOR'] = '1'
    env['FORCE_COLOR'] = '0'
    env['DEBUG_PRINT_LIMIT'] = '0'
    env['CI'] = '1'
    return env


def run(cmd, env=None, cwd=None):
    e = env or make_env()
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True, env=e, cwd=cwd
    )


def summarize_vitest(log_text, max_lines=60):
    text = ANSI_RE.sub('', log_text or '')
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines) and len(out) < max_lines:
        s = lines[i].strip()
        is_fail = s.startswith('FAIL') or ' x ' in lines[i] or ' ! ' in lines[i]
        is_err = 'AssertionError' in lines[i] or 'Error:' in lines[i]
        is_loc = bool(FILE_LOC_RE.search(lines[i]))
        if is_fail or is_err or is_loc:
            block = lines[i:i + 5]
            for b in block:
                if not b.lstrip().startswith('<'):
                    out.append(b)
            out.append('---')
            i += 1
        else:
            i += 1
    if not out:
        return '\n'.join(text.splitlines()[-max_lines:])
    return '\n'.join(out[:max_lines])


def run_frontend_checks(run_tests=True):
    env = make_env()
    cwd = FRONTEND_DIR if Path(FRONTEND_DIR).is_dir() else '.'

    print('running tsc (cwd={})...'.format(cwd))
    tsc = run('npx tsc --noEmit', env=env, cwd=cwd)
    if tsc.returncode != 0:
        print('tsc failed:')
        print(ANSI_RE.sub('', (tsc.stdout + tsc.stderr))[:3000])
        return tsc.returncode
    print('tsc ok')

    if not run_tests:
        return 0

    print('running vitest (cwd={})...'.format(cwd))
    log_dir = Path('bundles')
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / 'last_run.log'

    res = run('npx vitest run --reporter=dot', env=env, cwd=cwd)
    text = (res.stdout or '') + '\n' + (res.stderr or '')
    log_path.write_text(ANSI_RE.sub('', text), encoding='utf-8')

    if res.returncode != 0:
        print('vitest failed; summary (full log: bundles/last_run.log):')
        print(summarize_vitest(text))
        return res.returncode

    print('vitest ok (log: {})'.format(log_path))
    return 0


def git_commit(msg):
    run('git add -A')
    r = run('git commit -m "{}"'.format(msg))
    if r.returncode != 0:
        print('git commit failed:')
        print((r.stdout or '') + (r.stderr or ''))
        sys.exit(r.returncode)
    print('committed')


def main():
    ap = argparse.ArgumentParser(
        description='Apply a bundle and run frontend checks.'
    )
    ap.add_argument('bundle', help='path to bundle .txt file')
    ap.add_argument('--frontend', action='store_true', help='run tsc + vitest')
    ap.add_argument('--commit', default=None, help='git commit message')
    ap.add_argument('--dry-run', action='store_true', help='parse only, do not write')
    ap.add_argument('--no-test', action='store_true', help='skip vitest (still runs tsc)')
    args, extra = ap.parse_known_args()
    if extra:
        print('note: ignoring unknown flags: {}'.format(extra))

    path = Path(args.bundle)
    if not path.exists():
        print('bundle not found: {}'.format(path), file=sys.stderr)
        sys.exit(2)

    files = parse_bundle(path)
    if not files:
        print('no files parsed from bundle', file=sys.stderr)
        sys.exit(2)

    damage = _bundle_looks_damaged(path, files)
    if damage:
        print(
            'Bundle looks copied from rendered text. '
            'Use the copy button on the code block and try again.',
            file=sys.stderr,
        )
        print('  reason: {}'.format(damage), file=sys.stderr)
        sys.exit(3)

    if args.dry_run:
        for k in files:
            print('would write: {}'.format(k))
        return

    write_files(files)

    if args.frontend:
        rc = run_frontend_checks(run_tests=not args.no_test)
        if rc != 0:
            sys.exit(rc)

    if args.commit:
        git_commit(args.commit)


if __name__ == '__main__':
    main()
