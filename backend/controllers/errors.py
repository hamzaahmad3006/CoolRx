"""Domain exceptions and their mapping to the API error envelope.

Controllers raise these; the middleware turns them into `ApiErrorEnvelope`. The
mapping lives in one table so an error code cannot drift from the HTTP status it
is served with, and so adding a code forces a decision about both.

Nothing here imports FastAPI. A controller that raised an `HTTPException` would be
holding HTTP concerns, which SRS §16.1 puts in the route layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from http import HTTPStatus

from schemas.common import ApiErrorCode

#: Scalars only. A nested object here would tempt callers into returning model
#: internals or raw upstream payloads to the client.
DetailValue = str | int | float | bool


@dataclass(slots=True)
class CoolRxError(Exception):
    """Base class. Carries everything the envelope needs and nothing more."""

    message: str
    code: ApiErrorCode = "INTERNAL_ERROR"
    #: Named `field` to match the API envelope. It shadows `dataclasses.field`
    #: inside this class body, which is why the import is aliased to `dc_field`.
    field: str | None = None
    details: dict[str, DetailValue] = dc_field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.message)


@dataclass(slots=True)
class NotFoundError(CoolRxError):
    code: ApiErrorCode = "NOT_FOUND"


@dataclass(slots=True)
class ValidationFailedError(CoolRxError):
    code: ApiErrorCode = "VALIDATION_FAILED"


@dataclass(slots=True)
class AoiRejectedError(CoolRxError):
    """An AOI that failed pre-flight validation.

    Distinct from a generic validation failure because the specific code
    (area/coverage/geometry) drives which inline hint the AOI Studio shows.
    """

    code: ApiErrorCode = "VALIDATION_FAILED"


@dataclass(slots=True)
class JobAlreadyRunningError(CoolRxError):
    """A second analysis was requested while one is in flight.

    Refused rather than queued: two concurrent diagnose runs on one project would
    both spend credits to compute the same thing.
    """

    code: ApiErrorCode = "JOB_ALREADY_RUNNING"


@dataclass(slots=True)
class CreditsExhaustedError(CoolRxError):
    code: ApiErrorCode = "CREDITS_BELOW_RESERVE"


@dataclass(slots=True)
class UpstreamUnavailableError(CoolRxError):
    code: ApiErrorCode = "UPSTREAM_UNAVAILABLE"


@dataclass(slots=True)
class RateLimitedError(CoolRxError):
    code: ApiErrorCode = "RATE_LIMITED"


@dataclass(slots=True)
class UnauthorizedError(CoolRxError):
    code: ApiErrorCode = "UNAUTHORIZED"


@dataclass(slots=True)
class PreconditionMissingError(CoolRxError):
    """A dependency of the request has not been produced yet.

    Served as 409 rather than 404: the resource is legitimately absent for now
    (no diagnosis has run, the catalog is unpopulated), which is a different fact
    from "this identifier does not exist" and needs a different UI response.
    """

    code: ApiErrorCode = "VALIDATION_FAILED"


#: Error code → HTTP status. Every code in `ApiErrorCode` appears exactly once;
#: `test_error_mapping_is_exhaustive` fails the build if a new code is added
#: without a status, rather than letting it fall through to a 500.
STATUS_FOR_CODE: dict[ApiErrorCode, int] = {
    "AOI_AREA_EXCEEDED": HTTPStatus.UNPROCESSABLE_ENTITY,
    "AOI_OUTSIDE_COVERAGE": HTTPStatus.UNPROCESSABLE_ENTITY,
    "AOI_NOT_CLOSED": HTTPStatus.UNPROCESSABLE_ENTITY,
    "AOI_INVALID_GEOMETRY": HTTPStatus.UNPROCESSABLE_ENTITY,
    "DATE_OUT_OF_RANGE": HTTPStatus.UNPROCESSABLE_ENTITY,
    "GRANULARITY_INVALID": HTTPStatus.UNPROCESSABLE_ENTITY,
    "VALIDATION_FAILED": HTTPStatus.UNPROCESSABLE_ENTITY,
    # 402 rather than 503: the upstream is healthy, we are declining to spend.
    "CREDITS_BELOW_RESERVE": HTTPStatus.PAYMENT_REQUIRED,
    "RATE_LIMITED": HTTPStatus.TOO_MANY_REQUESTS,
    "JOB_ALREADY_RUNNING": HTTPStatus.CONFLICT,
    "UPSTREAM_UNAVAILABLE": HTTPStatus.SERVICE_UNAVAILABLE,
    "NOT_FOUND": HTTPStatus.NOT_FOUND,
    "UNAUTHORIZED": HTTPStatus.UNAUTHORIZED,
    "INTERNAL_ERROR": HTTPStatus.INTERNAL_SERVER_ERROR,
}


def status_for(code: ApiErrorCode) -> int:
    """HTTP status for an error code, defaulting to 500 on an unmapped one."""
    return int(STATUS_FOR_CODE.get(code, HTTPStatus.INTERNAL_SERVER_ERROR))
