"""Virus scanner abstraction.

Every uploaded file (sick notes, attachments, exports) is scanned before it is
stored or served. Two implementations:

  * NoOpScanner   - development default. Logs a warning and returns clean.
                    Never allowed in production.
  * ClamAVScanner - production. Talks to ClamAV over TCP.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ScanResult:
    """Result of a virus scan."""

    clean: bool
    engine: str
    detail: str | None = None


class VirusScanner(ABC):
    """Interface every scanner backend must implement."""

    @abstractmethod
    def scan(self, data: bytes) -> ScanResult:
        """Scan `data` and return a ScanResult."""