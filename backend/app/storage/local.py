"""LocalFileStorage — development default.

Writes files under <repo>/backend/var/storage. No cloud dependency.

Safe for a laptop, not for production: production requires at-rest encryption
and short-lived signed URLs, both of which need an object store.
"""
from __future__ import annotations

from pathlib import Path

from app.storage.base import Storage


class LocalFileStorage(Storage):
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        if key.startswith("/") or key.startswith("\\"):
            raise ValueError(f"Storage key must be relative, got {key!r}")
        candidate = (self._base_dir / key).resolve()
        base = self._base_dir.resolve()
        if base not in candidate.parents and candidate != base:
            raise ValueError(f"Storage key escapes base directory: {key!r}")
        return candidate

    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def load(self, key: str) -> bytes:
        path = self._path_for(key)
        if not path.exists():
            raise FileNotFoundError(f"Storage key not found: {key!r}")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path_for(key)
        if path.exists():
            path.unlink()

    def exists(self, key: str) -> bool:
        return self._path_for(key).exists()

    def signed_url(self, key: str, expires_in_seconds: int = 900) -> str:
        return self._path_for(key).as_uri()
