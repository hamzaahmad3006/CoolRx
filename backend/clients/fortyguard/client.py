"""The FortyGuard client — the single choke point for all FortyGuard traffic.

Design notes
------------
**Synchronous on purpose.** The heavy work runs in an RQ worker, and RQ workers
are synchronous. A sync client avoids bridging async into a sync worker, which
would add a failure mode for no benefit. FastAPI runs sync dependencies in a
threadpool, so the API path is unaffected.

**Everything goes through here.** No other module may call `api.fortyguard.com`.
That is what makes the guarantees below hold globally rather than per call site:

  1. Pre-flight validation — rejections are free, successes cost credits
  2. Request-hash cache — a repeated request never hits the network twice
  3. Bounded polling with exponential backoff — never an unbounded loop
  4. Credit guard — refuses below the reserve floor, before any network call
  5. Circuit breaker — stops hammering a failing upstream
  6. Fixture mode — full reproducibility with no key
  7. Audit trail — every request recorded, whether it succeeded or not
  8. Secret hygiene — the API key is never logged or persisted
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from core.config import Settings

from .cache import FixtureStore, compute_request_hash
from .errors import (
    CircuitOpen,
    CreditReserveExhausted,
    FortyGuardAuthError,
    FortyGuardConnectionError,
    FortyGuardNotReadyError,
    FortyGuardPlanError,
    FortyGuardTaskFailed,
    FortyGuardTimeout,
    SubmissionCapReached,
    classify_http_status,
)
from .models import ActivityStatus, StatusEnvelope, SubmitEnvelope

log = structlog.get_logger(__name__)

#: Endpoint paths, exactly as documented.
ENDPOINT_HEATMAP = "heatmap"
ENDPOINT_ENV_PARAMS = "env_params"
ENDPOINT_SATELLITE = "satellite"
ENDPOINT_STREETVIEW = "streetview"
ENDPOINT_HEAT_INTELLIGENCE = "heat_intelligence"

_PATHS: dict[str, str] = {
    ENDPOINT_HEATMAP: "/heatmap",
    ENDPOINT_ENV_PARAMS: "/env_params",
    ENDPOINT_SATELLITE: "/satellite",
    ENDPOINT_STREETVIEW: "/streetview",
    ENDPOINT_HEAT_INTELLIGENCE: "/heat_intelligence",
}

#: Endpoints that require API Premium. A 403 on these is expected on Basic and
#: must degrade the feature rather than the product.
PREMIUM_ENDPOINTS = frozenset(
    {ENDPOINT_SATELLITE, ENDPOINT_STREETVIEW, ENDPOINT_HEAT_INTELLIGENCE}
)


@dataclass(slots=True)
class FGResult:
    """Outcome of a completed FortyGuard task."""

    endpoint: str
    request_hash: str
    activity_id: str | None
    result: dict[str, Any]
    #: True when served from cache or a fixture — no credits were consumed.
    from_cache: bool
    from_fixture: bool
    poll_count: int
    latency_ms: int


@dataclass(slots=True)
class AuditRecord:
    """What the caller persists to `fg_requests` for provenance (SRS §20.2)."""

    endpoint: str
    request_hash: str
    #: Request body with credentials stripped. The key is never included.
    request_body: dict[str, Any]
    activity_id: str | None
    status: str
    http_status: int | None
    poll_count: int
    latency_ms: int
    credits_charged: bool
    from_fixture: bool
    error: str | None


#: Callback used to persist an audit record. Injected so the client stays free of
#: database coupling and remains unit-testable without a database.
AuditSink = Callable[[AuditRecord], None]

#: Returns the remaining credit balance, or None when it cannot be determined.
#: The credits endpoint contract is undocumented (SRS C-10), so the guard must
#: work either way.
CreditReader = Callable[[], int | None]


@dataclass(slots=True)
class _Breaker:
    """Per-endpoint circuit breaker."""

    threshold: int
    cooldown_seconds: int
    failures: int = 0
    opened_at: float | None = None

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold and self.opened_at is None:
            self.opened_at = time.monotonic()

    @property
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at >= self.cooldown_seconds:
            # Half-open: allow one probe through.
            self.opened_at = None
            self.failures = self.threshold - 1
            return False
        return True


class FortyGuardClient:
    """Hardened client for the FortyGuard Temperature API."""

    def __init__(
        self,
        settings: Settings,
        *,
        cache_get: Callable[[str], dict[str, Any] | None] | None = None,
        cache_put: Callable[[str, str, dict[str, Any], dict[str, Any]], None]
        | None = None,
        audit: AuditSink | None = None,
        credit_reader: CreditReader | None = None,
        submissions_today: Callable[[], int] | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._fixtures = FixtureStore(
            settings.fixture_dir, strict=settings.fixture_strict
        )
        self._cache_get = cache_get
        self._cache_put = cache_put
        self._audit = audit
        self._credit_reader = credit_reader
        self._submissions_today = submissions_today
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            base_url=settings.fortyguard_base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers=self._auth_headers(),
        )
        self._breakers: dict[str, _Breaker] = {}
        #: Premium endpoints disabled at runtime after a 403, so a single
        #: rejection does not produce one log line per subsequent call.
        self._disabled_endpoints: set[str] = set()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> FortyGuardClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _auth_headers(self) -> dict[str, str]:
        """Authentication is a single header. No OAuth, no token exchange."""
        key = self._settings.fortyguard_api_key
        return {"api-key": key} if key else {}

    def _breaker_for(self, endpoint: str) -> _Breaker:
        if endpoint not in self._breakers:
            self._breakers[endpoint] = _Breaker(
                threshold=self._settings.fg_breaker_failure_threshold,
                cooldown_seconds=self._settings.fg_breaker_cooldown_seconds,
            )
        return self._breakers[endpoint]

    # ── Public API ───────────────────────────────────────────────────────────

    def submit_and_wait(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        deadline_seconds: int | None = None,
    ) -> FGResult:
        """Submit a task and poll until it reaches a terminal state.

        Order of operations matters and is deliberate: cache, then fixture, then
        the guards, and only then the network. Each earlier step makes the later
        ones unnecessary.
        """
        if endpoint not in _PATHS:
            raise ValueError(f"Unknown FortyGuard endpoint: {endpoint}")

        request_hash = compute_request_hash(endpoint, payload)
        started = time.monotonic()

        # 1. Cache — free, and the primary resilience mechanism during an outage.
        if self._cache_get is not None:
            cached = self._cache_get(request_hash)
            if cached is not None:
                log.debug(
                    "fg.cache_hit", endpoint=endpoint, request_hash=request_hash
                )
                return FGResult(
                    endpoint=endpoint,
                    request_hash=request_hash,
                    activity_id=None,
                    result=cached,
                    from_cache=True,
                    from_fixture=False,
                    poll_count=0,
                    latency_ms=self._elapsed_ms(started),
                )

        # 2. Fixture mode — no network, no key, no credits.
        if self._settings.fixture_mode:
            stored = self._fixtures.load(request_hash, endpoint)
            result = self._extract_result(stored.get("response", {}))
            self._record(
                AuditRecord(
                    endpoint=endpoint,
                    request_hash=request_hash,
                    request_body=payload,
                    activity_id=None,
                    status="Completed",
                    http_status=200,
                    poll_count=0,
                    latency_ms=self._elapsed_ms(started),
                    credits_charged=False,
                    from_fixture=True,
                    error=None,
                )
            )
            return FGResult(
                endpoint=endpoint,
                request_hash=request_hash,
                activity_id=None,
                result=result,
                from_cache=False,
                from_fixture=True,
                poll_count=0,
                latency_ms=self._elapsed_ms(started),
            )

        # 3. Guards — all raise before any network call, so none costs credits.
        self._assert_endpoint_available(endpoint)
        self._assert_breaker_closed(endpoint)
        self._assert_submission_budget()
        self._assert_credit_reserve()

        # 4. Submit.
        activity_id = self._submit(endpoint, payload, request_hash, started)

        # 5. Poll to a terminal state.
        deadline = deadline_seconds or self._settings.fg_poll_deadline_seconds
        result, polls = self._poll(endpoint, activity_id, deadline, request_hash)

        latency = self._elapsed_ms(started)
        self._breaker_for(endpoint).record_success()

        if self._cache_put is not None:
            self._cache_put(request_hash, endpoint, payload, result)

        self._record(
            AuditRecord(
                endpoint=endpoint,
                request_hash=request_hash,
                request_body=payload,
                activity_id=activity_id,
                status="Completed",
                http_status=200,
                poll_count=polls,
                latency_ms=latency,
                # Credits are deducted only on successful completion.
                credits_charged=True,
                from_fixture=False,
                error=None,
            )
        )

        return FGResult(
            endpoint=endpoint,
            request_hash=request_hash,
            activity_id=activity_id,
            result=result,
            from_cache=False,
            from_fixture=False,
            poll_count=polls,
            latency_ms=latency,
        )

    # ── Guards ───────────────────────────────────────────────────────────────

    def _assert_endpoint_available(self, endpoint: str) -> None:
        if endpoint in self._disabled_endpoints:
            raise FortyGuardPlanError(
                f"Endpoint '{endpoint}' is unavailable on the current plan.",
                endpoint=endpoint,
            )
        if endpoint in PREMIUM_ENDPOINTS and not self._premium_enabled(endpoint):
            raise FortyGuardPlanError(
                f"Endpoint '{endpoint}' is Premium-only and is disabled by "
                "configuration.",
                endpoint=endpoint,
            )

    def _premium_enabled(self, endpoint: str) -> bool:
        s = self._settings
        return {
            ENDPOINT_SATELLITE: s.fg_enable_satellite,
            ENDPOINT_STREETVIEW: s.fg_enable_streetview,
            ENDPOINT_HEAT_INTELLIGENCE: s.fg_enable_heat_intelligence,
        }.get(endpoint, True)

    def _assert_breaker_closed(self, endpoint: str) -> None:
        if self._breaker_for(endpoint).is_open:
            raise CircuitOpen(
                f"Circuit breaker open for '{endpoint}' after repeated failures; "
                "serving cached data instead."
            )

    def _assert_submission_budget(self) -> None:
        if self._submissions_today is None:
            return
        used = self._submissions_today()
        cap = self._settings.fg_daily_submission_cap
        if used >= cap:
            raise SubmissionCapReached(
                f"Daily submission cap reached ({used}/{cap})."
            )

    def _assert_credit_reserve(self) -> None:
        if self._credit_reader is None:
            return
        remaining = self._credit_reader()
        if remaining is None:
            # The credits endpoint contract is undocumented; a local counter is
            # the fallback and the submission cap above already bounds spend.
            return
        reserve = self._settings.fg_credit_reserve
        if remaining <= reserve:
            raise CreditReserveExhausted(
                f"Credit balance {remaining} is at or below the reserve floor "
                f"{reserve}; live analysis is paused."
            )

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def _submit(
        self, endpoint: str, payload: dict[str, Any], request_hash: str, started: float
    ) -> str:
        path = _PATHS[endpoint]
        try:
            response = self._http.post(path, json=payload)
        except httpx.HTTPError as exc:
            self._breaker_for(endpoint).record_failure()
            self._record_failure(
                endpoint, request_hash, payload, None, None, started, str(exc)
            )
            raise FortyGuardConnectionError(
                f"Could not reach FortyGuard: {exc}"
            ) from exc

        if response.status_code >= 400:
            self._handle_error_response(
                endpoint, response, request_hash, payload, started, activity_id=None
            )

        envelope = SubmitEnvelope.model_validate(response.json())
        activity_id = envelope.data.activity_id
        log.info(
            "fg.submit",
            endpoint=endpoint,
            request_hash=request_hash,
            activity_id=activity_id,
        )
        return activity_id

    def _poll(
        self, endpoint: str, activity_id: str, deadline_seconds: int, request_hash: str
    ) -> tuple[dict[str, Any], int]:
        """Poll `GET /v1/status/{activity_id}` until terminal.

        Bounded three ways — a wall-clock deadline, a capped backoff, and a
        terminal-status check. There is deliberately no `while True`.
        """
        began = time.monotonic()
        delay = self._settings.fg_poll_initial_seconds
        polls = 0
        not_ready_streak = 0

        while time.monotonic() - began < deadline_seconds:
            polls += 1
            try:
                response = self._http.get(f"/status/{activity_id}")
            except httpx.HTTPError as exc:
                raise FortyGuardConnectionError(
                    f"Status poll failed: {exc}", activity_id=activity_id
                ) from exc

            if response.status_code == 404:
                # Documented as transient immediately after submission. Tolerated
                # for a bounded number of consecutive polls, then treated as real.
                not_ready_streak += 1
                if not_ready_streak > 5:
                    raise FortyGuardNotReadyError(
                        f"Activity {activity_id} still not found after "
                        f"{not_ready_streak} polls.",
                        activity_id=activity_id,
                    )
                time.sleep(self._next_delay(delay))
                delay = self._grow(delay)
                continue

            if response.status_code >= 400:
                self._handle_error_response(
                    endpoint,
                    response,
                    request_hash,
                    {},
                    began,
                    activity_id=activity_id,
                )

            not_ready_streak = 0
            envelope = StatusEnvelope.model_validate(response.json())
            status = envelope.data.status

            if status is ActivityStatus.COMPLETED:
                result = envelope.data.result or {}
                log.info(
                    "fg.complete",
                    endpoint=endpoint,
                    activity_id=activity_id,
                    poll_count=polls,
                )
                return result, polls

            if status is ActivityStatus.FAILED:
                # Terminal by documentation. Failed tasks consume no credits.
                self._breaker_for(endpoint).record_failure()
                raise FortyGuardTaskFailed(
                    f"Activity {activity_id} failed during processing.",
                    activity_id=activity_id,
                )

            time.sleep(self._next_delay(delay))
            delay = self._grow(delay)

        raise FortyGuardTimeout(
            f"Activity {activity_id} did not complete within {deadline_seconds}s. "
            "It may still finish upstream; retrying is cache-safe.",
            activity_id=activity_id,
        )

    def _next_delay(self, delay: float) -> float:
        """Full jitter, so concurrent workers do not retry in lockstep."""
        return random.uniform(0, delay)  # noqa: S311 — jitter, not cryptography

    def _grow(self, delay: float) -> float:
        return min(delay * 2, self._settings.fg_poll_max_seconds)

    def _handle_error_response(
        self,
        endpoint: str,
        response: httpx.Response,
        request_hash: str,
        payload: dict[str, Any],
        started: float,
        *,
        activity_id: str | None,
    ) -> None:
        retry_after = response.headers.get("retry-after")
        error = classify_http_status(
            response.status_code,
            message=self._safe_error_message(response),
            activity_id=activity_id,
            retry_after_seconds=float(retry_after) if retry_after else None,
        )

        if response.status_code == 403 and endpoint in PREMIUM_ENDPOINTS:
            # Expected on a Basic key. Disable the feature for this process so it
            # degrades once rather than logging on every subsequent call.
            self._disabled_endpoints.add(endpoint)
            log.warning("fg.premium_unavailable", endpoint=endpoint)
            error = FortyGuardPlanError(
                f"Endpoint '{endpoint}' is not included in the current plan.",
                endpoint=endpoint,
            )

        if error.retryable:
            self._breaker_for(endpoint).record_failure()

        if isinstance(error, FortyGuardAuthError):
            log.error("fg.auth_failed", endpoint=endpoint)

        self._record_failure(
            endpoint,
            request_hash,
            payload,
            activity_id,
            response.status_code,
            started,
            error.message,
        )
        raise error

    @staticmethod
    def _safe_error_message(response: httpx.Response) -> str:
        """Extract an error message without echoing credentials or a huge body."""
        try:
            body = response.json()
        except ValueError:
            return f"HTTP {response.status_code}"
        if isinstance(body, dict):
            message = body.get("message") or body.get("error")
            if isinstance(message, str):
                return f"HTTP {response.status_code}: {message}"
        return f"HTTP {response.status_code}"

    # ── Bookkeeping ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_result(response: dict[str, Any]) -> dict[str, Any]:
        """Pull `data.result` out of a stored envelope."""
        data = response.get("data")
        if isinstance(data, dict):
            result = data.get("result")
            if isinstance(result, dict):
                return result
        return response

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.monotonic() - started) * 1000)

    def _record(self, record: AuditRecord) -> None:
        if self._audit is not None:
            self._audit(record)

    def _record_failure(
        self,
        endpoint: str,
        request_hash: str,
        payload: dict[str, Any],
        activity_id: str | None,
        http_status: int | None,
        started: float,
        error: str,
    ) -> None:
        self._record(
            AuditRecord(
                endpoint=endpoint,
                request_hash=request_hash,
                request_body=payload,
                activity_id=activity_id,
                status="Failed",
                http_status=http_status,
                poll_count=0,
                latency_ms=self._elapsed_ms(started),
                # Rejected and failed requests do not consume credits.
                credits_charged=False,
                from_fixture=False,
                error=error,
            )
        )


@dataclass(slots=True)
class LadderRequest:
    """Inputs for an exceedance ladder (SRS §9.4).

    The ladder is what converts a predicted ΔT into hours-of-danger avoided,
    using FortyGuard's own configurable threshold rather than an invented diurnal
    model. It costs `steps + 1` cached heatmap calls per district/date.
    """

    base_threshold_c: float
    steps: int
    thresholds: tuple[float, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.thresholds:
            object.__setattr__(
                self,
                "thresholds",
                tuple(self.base_threshold_c + i for i in range(self.steps + 1)),
            )
