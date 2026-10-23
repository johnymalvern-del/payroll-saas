"""No source file in the repo may start with a byte-order mark.

A BOM on a .py file breaks Python 3.12 at compile time. A BOM on a .toml
file breaks pytest's own config reader. This test prevents either from
recurring, and names the offending file so the fix is one editor action.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", "var"}
SUFFIXES = {".py", ".ini", ".toml", ".json"}
BOM = b"\xef\xbb\xbf"


def _iter_files() -> list[Path]:
    out: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        if path.suffix in SUFFIXES:
            out.append(path)
    return out


def test_no_bom_anywhere() -> None:
    offenders = []
    for path in _iter_files():
        with path.open("rb") as fh:
            head = fh.read(3)
        if head == BOM:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], (
        "Files starting with a UTF-8 BOM (save them as 'UTF-8 without BOM'):\n  "
        + "\n  ".join(offenders)
    )