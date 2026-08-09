"""Typed exceptions for FortyGuard API failures.

One class per documented status class, because the correct retry behaviour
differs for each and a single generic exception would erase that distinction
(SRS §11.2).

Retry policy:
  429, 5xx, connection errors  → retry with exponential backoff
  404 immediately post-submit  → retry (documented transient state)
  400, 401, 403, 422           → never retry; the request itself is wrong
  activity status "Failed"     → never retry; terminal
"""

from __future__ import annotations


class FortyGuardError(Exception):
    """Base class for every FortyGuard failure."""

    #: Whether a retry could plausibly succeed.
    retryable: bool = False

    def __init__(self, message: str, *, activity_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        #: Recorded even on failure so a task can be traced with FortyGuard.
        self.activity_id = activity_id


# ── Non-retryable: the request is wrong ──────────────────────────────────────


class FortyGuardValidationError(FortyGuardError):
    """400 / 422 — malformed request or failed validation.

    Not charged against the credit balance, which is precisely why pre-flight
    validation is worth doing: a rejection is free, a success is not.
    """

    retryable = False


class FortyGuardAuthError(FortyGuardError):
    """401 — missing or invalid API key. Fail fast, do not retry."""

    retryable = False


class FortyGuardPlanError(FortyGuardError):
    """403 — the plan does not include this endpoint.

    Expected for Premium-only endpoints on a Basic key. The caller should disable
    the corresponding feature flag for the session and continue on the Basic
    path rather than treating this as an outage (SRS R-04).
    """

    retryable = False

    def __init__(self, message: str, *, endpoint: str) -> None:
        super().__init__(message)
        self.endpoint = endpoint


# ── Retryable: transient ─────────────────────────────────────────────────────


class FortyGuardNotReadyError(FortyGuardError):
    """404 shortly after submission.

    The documentation lists 404 as meaning "activity not found **or temporarily
    unavailable immediately after submission**", so this is an expected
    transient state and must not be treated as a permanent failure.
    """

    retryable = True


class FortyGuardRateLimitError(FortyGuardError):
    """429 — rate limited. Published limits are undocumented (SRS C-11)."""

    retryable = True

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class FortyGuardServerError(FortyGuardError):
    """5xx — server-side processing error."""

    retryable = True


class FortyGuardConnectionError(FortyGuardError):
    """Network failure before any response was received."""

    retryable = True


# ── Terminal task outcomes ───────────────────────────────────────────────────


class FortyGuardTaskFailed(FortyGuardError):
    """Activity reached status "Failed".

    Terminal by documentation — stop polling and record the activity id. Failed
    tasks do not consume credits.
    """

    retryable = False


class FortyGuardTimeout(FortyGuardError):
    """The task did not reach a terminal state within the wall-clock deadline.

    The activity may still complete upstream, so the id is retained and a retry
    is cache-safe.
    """

    retryable = True


# ── Client-side guards ───────────────────────────────────────────────────────


class CreditReserveExhausted(FortyGuardError):
    """Refused locally: the credit balance is at or below the reserve floor.

    Raised before any network call, so it never consumes credits.
    """

    retryable = False


class SubmissionCapReached(FortyGuardError):
    """Refused locally: the configured daily submission ceiling was hit."""

    retryable = False


class CircuitOpen(FortyGuardError):
    """Refused locally: the circuit breaker is open after repeated failures."""

    retryable = True


class FixtureMissing(FortyGuardError):
    """No committed fixture matches this request in fixture mode.

    Raised loudly rather than silently falling through to a live call — a
    fixture-mode run that quietly hits the network would spend credits and
    invalidate the reproducibility guarantee (SRS FR-022).
    """

    retryable = False

    def __init__(self, request_hash: str, endpoint: str) -> None:
        super().__init__(
            f"No fixture for {endpoint} request_hash={request_hash}. "
            "Record it, or run with FIXTURE_MODE=false to fetch live."
        )
        self.request_hash = request_hash
        self.endpoint = endpoint


def classify_http_status(
    status_code: int,
    *,
    message: str,
    activity_id: str | None = None,
    retry_after_seconds: float | None = None,
) -> FortyGuardError:
    """Map an HTTP status onto the correct typed exception."""
    if status_code in (400, 422):
        return FortyGuardValidationError(message, activity_id=activity_id)
    if status_code == 401:
        return FortyGuardAuthError(message, activity_id=activity_id)
    if status_code == 404:
        return FortyGuardNotReadyError(message, activity_id=activity_id)
    if status_code == 429:
        return FortyGuardRateLimitError(
            message, retry_after_seconds=retry_after_seconds
        )
    if status_code >= 500:
        return FortyGuardServerError(message, activity_id=activity_id)
    return FortyGuardError(message, activity_id=activity_id)
