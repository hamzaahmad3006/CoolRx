"""Tests for the error envelope.

Every failure the API can produce must arrive in one shape with a correlation id and
nothing internal in it. These are the tests that keep a new endpoint from inventing a
second error format the client has to special-case.
"""

from __future__ import annotations

import typing
from collections.abc import Iterator

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from clients.fortyguard.errors import (
    CreditReserveExhausted,
    FortyGuardAuthError,
    FortyGuardRateLimitError,
    FortyGuardTimeout,
)
from controllers.errors import (
    STATUS_FOR_CODE,
    AoiRejectedError,
    CoolRxError,
    JobAlreadyRunningError,
    NotFoundError,
    status_for,
)
from middleware.correlation import CorrelationIdMiddleware
from middleware.errors import register_error_handlers
from schemas.common import ApiErrorCode, RequestModel


# ═════════════════════════════════════════════════════════════════════════════
# The mapping table
# ═════════════════════════════════════════════════════════════════════════════


def test_error_mapping_is_exhaustive() -> None:
    """Every ApiErrorCode has an explicit HTTP status.

    Without this, a code added to the schema without a status silently becomes a
    500 — the client would show "something went wrong" for what is really a
    validation failure.
    """
    declared = set(typing.get_args(ApiErrorCode))
    mapped = set(STATUS_FOR_CODE)
    assert declared - mapped == set(), f"unmapped codes: {sorted(declared - mapped)}"
    assert mapped - declared == set(), f"stale codes: {sorted(mapped - declared)}"


def test_credits_exhausted_is_402_not_503() -> None:
    """The upstream is healthy; we are declining to spend. That is not an outage."""
    assert status_for("CREDITS_BELOW_RESERVE") == 402


def test_job_conflict_is_409() -> None:
    assert status_for("JOB_ALREADY_RUNNING") == 409


def test_unknown_code_falls_back_to_500() -> None:
    assert status_for("NOT_A_REAL_CODE") == 500  # type: ignore[arg-type]


# ═════════════════════════════════════════════════════════════════════════════
# Envelope shape over HTTP
# ═════════════════════════════════════════════════════════════════════════════


class _Body(RequestModel):
    count: int


@pytest.fixture
def client() -> Iterator[TestClient]:
    """An app whose only job is to raise, so the handlers are what is tested."""
    router = APIRouter()

    @router.get("/boom/domain")
    def _domain() -> None:
        raise NotFoundError(message="No such widget.", field="widgetId")

    @router.get("/boom/aoi")
    def _aoi() -> None:
        raise AoiRejectedError(
            message="AOI is 63.20 mi², above the 10.00 mi² limit.",
            code="AOI_AREA_EXCEEDED",
            field="aoi",
            details={"areaSqMi": 63.2},
        )

    @router.get("/boom/conflict")
    def _conflict() -> None:
        raise JobAlreadyRunningError(message="Already running.")

    @router.get("/boom/upstream")
    def _upstream() -> None:
        raise FortyGuardAuthError("401 invalid api-key sk-live-abcdef123456")

    @router.get("/boom/ratelimited")
    def _ratelimited() -> None:
        raise FortyGuardRateLimitError("429 slow down")

    @router.get("/boom/timeout")
    def _timeout() -> None:
        raise FortyGuardTimeout("deadline exceeded after 600s")

    @router.get("/boom/credits")
    def _credits() -> None:
        raise CreditReserveExhausted("balance 40000 below reserve 50000")

    @router.get("/boom/unexpected")
    def _unexpected() -> None:
        raise ZeroDivisionError("division by zero in a private calculation")

    @router.post("/echo")
    def _echo(body: _Body) -> dict[str, int]:
        return {"count": body.count}

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_error_handlers(app)
    app.include_router(router)

    # raise_server_exceptions=False so the handler's response is observed rather
    # than the exception being re-raised into the test.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _error(response: object) -> dict[str, object]:
    body = response.json()  # type: ignore[attr-defined]
    assert set(body) == {"error"}, "the envelope has exactly one top-level key"
    error = body["error"]
    assert isinstance(error, dict)
    return error


def test_domain_error_produces_the_envelope(client: TestClient) -> None:
    response = client.get("/boom/domain")
    assert response.status_code == 404

    error = _error(response)
    assert set(error) == {"code", "message", "field", "details", "correlationId"}
    assert error["code"] == "NOT_FOUND"
    assert error["message"] == "No such widget."
    assert error["field"] == "widgetId"


def test_specific_aoi_code_survives_to_the_client(client: TestClient) -> None:
    """The specific code drives which inline hint the AOI Studio shows."""
    response = client.get("/boom/aoi")
    assert response.status_code == 422

    error = _error(response)
    assert error["code"] == "AOI_AREA_EXCEEDED"
    assert error["field"] == "aoi"
    assert error["details"] == {"areaSqMi": 63.2}


def test_conflict_maps_to_409(client: TestClient) -> None:
    assert client.get("/boom/conflict").status_code == 409


def test_every_error_carries_a_correlation_id(client: TestClient) -> None:
    """It is the only link between what a user saw and a server log line."""
    for path in (
        "/boom/domain",
        "/boom/aoi",
        "/boom/upstream",
        "/boom/unexpected",
    ):
        error = _error(client.get(path))
        assert error["correlationId"], f"{path} has no correlation id"


def test_correlation_id_is_echoed_in_the_header(client: TestClient) -> None:
    response = client.get(
        "/boom/domain", headers={"X-Correlation-Id": "req_test_12345"}
    )
    assert response.headers["X-Correlation-Id"] == "req_test_12345"
    assert _error(response)["correlationId"] == "req_test_12345"


# ═════════════════════════════════════════════════════════════════════════════
# Nothing internal leaks
# ═════════════════════════════════════════════════════════════════════════════


def test_upstream_credentials_never_reach_the_client(client: TestClient) -> None:
    """An auth failure's detail can contain the API key. It must not be echoed."""
    response = client.get("/boom/upstream")
    assert response.status_code == 503

    raw = response.text
    assert "sk-live-abcdef123456" not in raw
    assert "invalid api-key" not in raw

    error = _error(response)
    # Reported as an upstream problem, not our 401: the user did not supply the key
    # and cannot fix it.
    assert error["code"] == "UPSTREAM_UNAVAILABLE"
    assert error["details"] == {"upstream": "FortyGuardAuthError"}


def test_unexpected_exception_leaks_no_internals(client: TestClient) -> None:
    response = client.get("/boom/unexpected")
    assert response.status_code == 500

    raw = response.text
    for leaked in ("ZeroDivisionError", "division by zero", "Traceback", "main.py"):
        assert leaked not in raw, f"{leaked!r} must not appear in a response body"

    error = _error(response)
    assert error["code"] == "INTERNAL_ERROR"
    assert error["correlationId"]


def test_upstream_rate_limit_maps_to_429(client: TestClient) -> None:
    response = client.get("/boom/ratelimited")
    assert response.status_code == 429
    assert _error(response)["code"] == "RATE_LIMITED"


def test_upstream_timeout_message_mentions_the_activity_is_recorded(
    client: TestClient,
) -> None:
    """A timed-out task may still complete, so the user is told it was recorded."""
    error = _error(client.get("/boom/timeout"))
    assert "activity id" in str(error["message"]).lower()


def test_credit_exhaustion_maps_to_402_and_offers_a_fallback(
    client: TestClient,
) -> None:
    """P5: never a dead end — the response names what still works."""
    response = client.get("/boom/credits")
    assert response.status_code == 402

    error = _error(response)
    assert error["code"] == "CREDITS_BELOW_RESERVE"
    assert "fixture" in str(error["message"]).lower()


# ═════════════════════════════════════════════════════════════════════════════
# Request validation uses the same envelope
# ═════════════════════════════════════════════════════════════════════════════


def test_pydantic_422_is_reshaped_into_the_envelope(client: TestClient) -> None:
    """FastAPI's default 422 body is a list — a second shape the client would parse."""
    response = client.post("/echo", json={"count": "not-a-number"})
    assert response.status_code == 422

    error = _error(response)
    assert error["code"] == "VALIDATION_FAILED"
    assert error["field"] == "count", "the failing field is named for the UI"
    assert error["details"] == {"errorCount": 1}


def test_unknown_field_is_reported_not_ignored(client: TestClient) -> None:
    response = client.post("/echo", json={"count": 1, "sneaky": True})
    assert response.status_code == 422
    assert _error(response)["code"] == "VALIDATION_FAILED"


def test_404_on_an_unknown_path_uses_the_envelope(client: TestClient) -> None:
    response = client.get("/no/such/route")
    assert response.status_code == 404
    assert _error(response)["code"] == "NOT_FOUND"


def test_domain_error_defaults_to_internal_error_code() -> None:
    """A bare CoolRxError is a 500, so a forgotten code cannot masquerade as a 4xx."""
    error = CoolRxError(message="something")
    assert error.code == "INTERNAL_ERROR"
    assert status_for(error.code) == 500
