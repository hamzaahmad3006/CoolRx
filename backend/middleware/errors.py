"""Error handling — one envelope for every failure.

Registered as exception handlers rather than as middleware, because FastAPI resolves
handlers by exception type and that keeps the mapping declarative.

Three rules hold for every response produced here:

  1. **One shape.** Every non-2xx body is an `ApiErrorEnvelope`, so the client has
     exactly one parser and no endpoint needs a special case.
  2. **The correlation id is always present.** It is what makes a user-reported
     error traceable to a server log line, so it is included even on a 500.
  3. **Internal detail never leaks.** An unexpected exception is logged with its
     traceback and returned as a generic message. A stack trace or a database error
     string in a response body is an information disclosure, and it is also useless
     to the person reading it.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from clients.fortyguard.errors import (
    CreditReserveExhausted,
    FortyGuardAuthError,
    FortyGuardConnectionError,
    FortyGuardError,
    FortyGuardPlanError,
    FortyGuardRateLimitError,
    FortyGuardServerError,
    FortyGuardTaskFailed,
    FortyGuardTimeout,
    FortyGuardValidationError,
    SubmissionCapReached,
)
from controllers.errors import CoolRxError, DetailValue, status_for
from middleware.correlation import HEADER_NAME
from schemas.common import ApiErrorCode, ApiErrorDetail, ApiErrorEnvelope

log = structlog.get_logger(__name__)


def _correlation_id(request: Request) -> str:
    """The request's correlation id, generating one if the middleware was skipped."""
    return request.headers.get(HEADER_NAME) or f"req_{uuid.uuid4().hex[:16]}"


def error_response(
    request: Request,
    *,
    code: ApiErrorCode,
    message: str,
    status_code: int,
    field: str | None = None,
    details: dict[str, DetailValue] | None = None,
) -> JSONResponse:
    """Build an error-envelope response.

    Public because middleware needs it. An exception raised inside a
    `BaseHTTPMiddleware` never reaches FastAPI's exception handlers — Starlette runs
    `BaseHTTPMiddleware` outside the layer that dispatches them, so a raise there
    escapes as an unhandled 500. Middleware must therefore *return* this rather than
    raise a domain error, or a rate-limited request would tell the user "something
    went wrong" instead of "slow down".
    """
    return _envelope(
        request,
        code=code,
        message=message,
        status_code=status_code,
        field=field,
        details=details,
    )


def _envelope(
    request: Request,
    *,
    code: ApiErrorCode,
    message: str,
    status_code: int,
    field: str | None = None,
    details: dict[str, DetailValue] | None = None,
) -> JSONResponse:
    correlation_id = _correlation_id(request)
    body = ApiErrorEnvelope(
        error=ApiErrorDetail(
            code=code,
            message=message,
            field=field,
            details=details or {},
            correlation_id=correlation_id,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(by_alias=True),
        headers={HEADER_NAME: correlation_id},
    )


#: FortyGuard failure → our error code. Mapped explicitly so an upstream problem
#: reaches the client as something it can act on, rather than as a generic 500.
_FG_CODE: dict[type[FortyGuardError], ApiErrorCode] = {
    FortyGuardValidationError: "VALIDATION_FAILED",
    FortyGuardAuthError: "UPSTREAM_UNAVAILABLE",
    FortyGuardPlanError: "UPSTREAM_UNAVAILABLE",
    FortyGuardRateLimitError: "RATE_LIMITED",
    FortyGuardServerError: "UPSTREAM_UNAVAILABLE",
    FortyGuardConnectionError: "UPSTREAM_UNAVAILABLE",
    FortyGuardTaskFailed: "UPSTREAM_UNAVAILABLE",
    FortyGuardTimeout: "UPSTREAM_UNAVAILABLE",
    CreditReserveExhausted: "CREDITS_BELOW_RESERVE",
    SubmissionCapReached: "CREDITS_BELOW_RESERVE",
}

#: Messages shown to users for upstream failures.
#:
#: An auth failure is reported as an upstream problem rather than as our 401: the
#: user did not supply the API key and cannot fix it, so telling them they are
#: unauthorised would send them looking for a credential they do not have.
_FG_MESSAGE: dict[type[FortyGuardError], str] = {
    FortyGuardAuthError: (
        "The temperature service rejected our credentials. Cached and fixture data "
        "remain available."
    ),
    FortyGuardPlanError: (
        "This analysis needs a FortyGuard plan feature that is not enabled on our "
        "account."
    ),
    FortyGuardRateLimitError: (
        "The temperature service is rate limiting us. Try again shortly."
    ),
    FortyGuardTimeout: (
        "The temperature service did not finish in time. The task may still "
        "complete; its activity id is recorded."
    ),
    FortyGuardTaskFailed: (
        "The temperature service reported that the analysis failed. Its activity id "
        "is recorded for follow-up."
    ),
}

_FG_FALLBACK = (
    "The temperature service is unavailable. Cached and fixture data remain "
    "available."
)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(CoolRxError)
    async def _handle_domain(request: Request, exc: CoolRxError) -> JSONResponse:
        status_code = status_for(exc.code)
        # 4xx is expected traffic — a rejected AOI is the validator working — so it
        # is logged at info. Only 5xx is an error on our side.
        log_at = log.error if status_code >= 500 else log.info
        log_at(
            "request.rejected",
            code=exc.code,
            field=exc.field,
            status=status_code,
            detail=exc.message,
        )
        return _envelope(
            request,
            code=exc.code,
            message=exc.message,
            status_code=status_code,
            field=exc.field,
            details=exc.details,
        )

    @app.exception_handler(FortyGuardError)
    async def _handle_fortyguard(
        request: Request, exc: FortyGuardError
    ) -> JSONResponse:
        code = _FG_CODE.get(type(exc), "UPSTREAM_UNAVAILABLE")
        message = _FG_MESSAGE.get(type(exc), _FG_FALLBACK)

        # The upstream detail goes to the log, not to the client: it can contain
        # request internals, and it is not actionable for the user.
        log.error(
            "upstream.failed",
            exception=type(exc).__name__,
            detail=str(exc),
            code=code,
        )
        return _envelope(
            request,
            code=code,
            message=message,
            status_code=status_for(code),
            details={"upstream": type(exc).__name__},
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Reshape pydantic's 422 into our envelope.

        FastAPI's default body is a list of pydantic errors, which is a second error
        shape the client would have to parse. The first error's location becomes
        `field` so the UI can attach the message to the right input.
        """
        errors = exc.errors()
        first = errors[0] if errors else {}
        location = [str(part) for part in first.get("loc", []) if part != "body"]

        return _envelope(
            request,
            code="VALIDATION_FAILED",
            message=str(first.get("msg", "Request validation failed.")),
            status_code=422,
            field=".".join(location) or None,
            details={"errorCount": len(errors)},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code: ApiErrorCode = "NOT_FOUND" if exc.status_code == 404 else "INTERNAL_ERROR"
        if exc.status_code == 401:
            code = "UNAUTHORIZED"
        elif exc.status_code == 429:
            code = "RATE_LIMITED"
        return _envelope(
            request,
            code=code,
            message=str(exc.detail),
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        """Last resort. Logs the traceback, returns nothing internal.

        The correlation id in the response is the link between what the user saw and
        the traceback in the logs, which is why it is never omitted here.
        """
        correlation_id = _correlation_id(request)
        log.exception(
            "request.unhandled",
            exception=type(exc).__name__,
            path=request.url.path,
            correlation_id=correlation_id,
        )
        return _envelope(
            request,
            code="INTERNAL_ERROR",
            message=(
                "Something went wrong on our side. Quote the correlation id below "
                "if you report this."
            ),
            status_code=500,
            details={"correlationId": correlation_id},
        )
