"""Rate limiting for the endpoints that cost money.

Scoped to write endpoints only. A limit on reads would throttle the map panning
that makes the demo feel responsive, while the endpoints worth protecting are the
few that enqueue work and spend FortyGuard credits.

In-memory, per-process, fixed-window. That is the right amount of machinery for a
single-instance hackathon deployment and is documented as such: with more than one
worker process each gets its own window, so the effective limit multiplies. Redis
would fix that, and is not worth the dependency here.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger(__name__)

#: Only these paths are limited. Matched by suffix so the project id in the path
#: does not need a pattern.
COSTLY_SUFFIXES: tuple[str, ...] = ("/diagnose", "/plans", "/verify")

WINDOW_SECONDS = 60.0
MAX_REQUESTS_PER_WINDOW = 6


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        *,
        window_seconds: float = WINDOW_SECONDS,
        max_requests: int = MAX_REQUESTS_PER_WINDOW,
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._window = window_seconds
        self._max = max_requests
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method != "POST" or not self._is_costly(request.url.path):
            return await call_next(request)

        key = self._client_key(request)
        now = time.monotonic()
        hits = self._hits[key]

        # Drop timestamps that have aged out of the window.
        cutoff = now - self._window
        while hits and hits[0] < cutoff:
            hits.popleft()

        if len(hits) >= self._max:
            retry_after = max(1, int(self._window - (now - hits[0])))
            log.warning(
                "rate_limit.rejected",
                path=request.url.path,
                client=key,
                hits=len(hits),
                retry_after_s=retry_after,
            )
            # Returned, not raised. An exception thrown inside a BaseHTTPMiddleware
            # bypasses FastAPI's exception handlers entirely and surfaces as an
            # unhandled 500, so the user would be told "something went wrong" rather
            # than "slow down".
            from middleware.errors import error_response

            response = error_response(
                request,
                code="RATE_LIMITED",
                message=(
                    "Too many analysis requests. Wait a moment before starting "
                    "another."
                ),
                status_code=429,
                details={"retryAfterSeconds": retry_after},
            )
            # The standard header, so a well-behaved client backs off correctly
            # without parsing the body.
            response.headers["Retry-After"] = str(retry_after)
            return response

        hits.append(now)
        return await call_next(request)

    @staticmethod
    def _is_costly(path: str) -> bool:
        return any(path.rstrip("/").endswith(suffix) for suffix in COSTLY_SUFFIXES)

    @staticmethod
    def _client_key(request: Request) -> str:
        """Identify the caller.

        `X-Forwarded-For`'s first entry is used when present, since the direct peer
        behind a proxy is the proxy itself and would bucket every user together.
        It is spoofable, which is acceptable here: this limit protects a credit
        budget from accidental double-clicks, not from a determined attacker.
        """
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"
