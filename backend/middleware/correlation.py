"""Correlation-ID middleware.

Every response carries a correlation id, and every log line emitted while
handling that request carries the same one. That is what makes a user-reported
error traceable to server logs — the id is surfaced in the UI's error state
(SRS §23.1, §27.5).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger(__name__)

HEADER_NAME = "X-Correlation-Id"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(HEADER_NAME)
        correlation_id = incoming or f"req_{uuid.uuid4().hex[:16]}"

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        started = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - started) * 1000)

        response.headers[HEADER_NAME] = correlation_id

        log.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response
