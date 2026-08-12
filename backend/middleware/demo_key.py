"""Demo-key gate for credit-spending endpoints (SRS §18.2).

The key is published in the README so a judge can deliberately exercise the live
path. It is not a secret and is not pretending to be one — its job is to make
spending credits an explicit act rather than something a crawler or a stray
double-click can trigger. The rate limit and the daily ceiling bound the damage if
it leaks, which is the right trade for a hackathon: open enough to be judged,
bounded enough not to be drained.

Two details matter despite that modest threat model:

  * **Constant-time comparison.** `secrets.compare_digest` rather than `==`, per SRS
    §18.7. The leak a naive comparison allows is small, but the fix costs nothing.
  * **The key is never logged.** It is redacted at the log formatter in `main.py`, so
    no call site here can leak it by accident.

Reads are ungated. Gating them would break the fixture-mode demo, which must work
with no key at all.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.config import Settings, get_settings

log = structlog.get_logger(__name__)

HEADER_NAME = "X-Demo-Key"

#: Path suffixes that can spend FortyGuard credits. Matched by suffix so the
#: identifiers embedded in the path need no pattern.
GATED_SUFFIXES: tuple[str, ...] = ("/diagnose", "/plans", "/verify")


class DemoKeyMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        *,
        settings_provider: Callable[[], Settings] = get_settings,
    ) -> None:
        """`settings_provider` is injected rather than read via FastAPI DI.

        Middleware runs outside the dependency-injection graph, so
        `app.dependency_overrides` cannot reach a `get_settings()` called in here —
        a test that overrode it would silently exercise the real environment and
        conclude the gate works when it never ran.
        """
        super().__init__(app)  # type: ignore[arg-type]
        self._settings_provider = settings_provider

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method != "POST" or not _is_gated(request.url.path):
            return await call_next(request)

        settings = self._settings_provider()

        # No key configured means the gate is off. Permitted in development so the
        # local stack needs no setup; `Settings` refuses to start in production
        # without one, so this cannot silently disable the gate where it matters.
        if settings.demo_key is None:
            return await call_next(request)

        # Fixture mode spends nothing, so gating it would only obstruct the demo.
        if settings.fixture_mode:
            return await call_next(request)

        supplied = request.headers.get(HEADER_NAME)
        if supplied is None or not secrets.compare_digest(supplied, settings.demo_key):
            log.warning(
                "demo_key.rejected",
                path=request.url.path,
                supplied=supplied is not None,
            )
            # Returned, not raised: an exception from inside a BaseHTTPMiddleware
            # bypasses FastAPI's exception handlers and becomes a 500, which would
            # tell the caller the server broke rather than that a header is missing.
            from middleware.errors import error_response

            return error_response(
                request,
                code="UNAUTHORIZED",
                message=(
                    "This endpoint spends API credits and needs the demo key. It is "
                    "published in the project README."
                ),
                status_code=401,
                field=HEADER_NAME,
            )

        return await call_next(request)


def _is_gated(path: str) -> bool:
    return any(path.rstrip("/").endswith(suffix) for suffix in GATED_SUFFIXES)
