"""Storage abstraction.

Every place that reads or writes a file (payslip PDFs, sick-note attachments,
biometric templates stored as encrypted blobs, exports) goes through the
`Storage` interface. Two implementations:

  * LocalFileStorage   — development default, no external services required
  * S3Storage          — production, MinIO in dev-compose, AWS S3 or equivalent

The `get_storage()` factory in factory.py decides which one the app uses.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Storage(ABC):
    """Interface every storage backend must implement."""

    @abstractmethod
    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        """Write `data` under `key`. Overwrites any existing object at `key`."""

    @abstractmethod
    def load(self, key: str) -> bytes:
        """Read the bytes stored at `key`. Raises FileNotFoundError if absent."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete the object at `key`. No-op if it does not exist."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return True if an object at `key` exists and is readable."""

    @abstractmethod
    def signed_url(self, key: str, expires_in_seconds: int = 900) -> str:
        """Return a URL the caller can fetch to read `key` for a limited time.

        LocalFileStorage returns a file:// URL — safe for local development
        where the process already has read permission. S3Storage returns a
        pre-signed HTTPS URL. Production code must only accept signed URLs,
        never a public bucket.
        """
