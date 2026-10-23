
"""Request-id middleware.

The request id is stored in a ContextVar so every log line inside the
request carries it. See tenant_routing.tenant_context for why we use
`set(None)` instead of `reset(token)` in the finally block.
"""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_ctx


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assigns and propagates an X-Request-Id header; the id is visible in logs."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        request_id_ctx.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.set(None)
        response.headers["X-Request-Id"] = rid
        return response
