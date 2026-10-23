"""ClamAVScanner - production scanner.

Talks to a ClamAV daemon over TCP (host:port from settings). The ClamAV
service is expected to be reachable; if it is not, scan() raises and the
upload fails closed (which is what we want - an unscanned file must never
be stored).
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.scanner.base import ScanResult, VirusScanner

log = get_logger("app.scanner.clamav")


class ClamAVScanner(VirusScanner):
    def __init__(self, host: str, port: int) -> None:
        # Import here so dev without ClamAV does not need the clamd package installed
        import clamd  # noqa: F401

        self._host = host
        self._port = port
        self._client = clamd.ClamdNetworkSocket(host=host, port=port, timeout=30)

    def scan(self, data: bytes) -> ScanResult:
        try:
            result = self._client.instream(__import__("io").BytesIO(data))
        except Exception as exc:  # noqa: BLE001 - fail closed
            log.error("scanner.clamav.error", error=str(exc))
            raise
        # result is a dict like {'stream': ('OK', None)} or {'stream': ('FOUND', 'Eicar-Test-Signature')}
        stream = result.get("stream") if isinstance(result, dict) else None
        if not stream:
            log.error("scanner.clamav.bad_response", result=str(result))
            return ScanResult(clean=False, engine="clamav", detail=f"unexpected response: {result}")
        status, signature = stream
        if status == "OK":
            return ScanResult(clean=True, engine="clamav")
        return ScanResult(clean=False, engine="clamav", detail=str(signature))