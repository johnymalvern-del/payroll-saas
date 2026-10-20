from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def _envelope(
    code: str,
    message: str,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


async def app_error_handler(_req: Request, exc: AppError) -> JSONResponse:
    return _envelope(exc.code, exc.message, exc.status_code, exc.details)


async def http_exception_handler(_req: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "error"
    return _envelope("http_error", message, exc.status_code)


async def validation_exception_handler(
    _req: Request, exc: RequestValidationError
) -> JSONResponse:
    return _envelope(
        "validation_error",
        "Request validation failed",
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        {"errors": exc.errors()},
    )