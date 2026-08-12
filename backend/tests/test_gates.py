"""Tests for the rate limiter and the demo-key gate.

Both exist to protect the FortyGuard credit balance, so the assertions that matter are
about what they *don't* block: reads must stay open or the fixture-mode demo breaks,
and GETs must never be throttled or panning the map would stutter.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from core.config import Settings, get_settings
from middleware.correlation import CorrelationIdMiddleware
from middleware.demo_key import HEADER_NAME, DemoKeyMiddleware
from middleware.errors import register_error_handlers
from middleware.rate_limit import RateLimitMiddleware

DEMO_KEY = "demo-key-for-tests"


def _router() -> APIRouter:
    router = APIRouter()

    @router.post("/projects/{project_id}/diagnose")
    def _diagnose(project_id: str) -> dict[str, str]:
        return {"ok": project_id}

    @router.post("/projects/{project_id}/plans")
    def _plans(project_id: str) -> dict[str, str]:
        return {"ok": project_id}

    @router.get("/projects/{project_id}/tiles")
    def _tiles(project_id: str) -> dict[str, str]:
        return {"ok": project_id}

    @router.post("/projects")
    def _create() -> dict[str, bool]:
        return {"created": True}

    return router


def _app(settings: Settings, *, max_requests: int = 3) -> FastAPI:
    app = FastAPI()
    # Settings are injected into the middleware explicitly. Middleware runs outside
    # the dependency-injection graph, so `dependency_overrides` alone would leave the
    # gate reading the real environment and the test would pass without ever
    # exercising it.
    app.add_middleware(DemoKeyMiddleware, settings_provider=lambda: settings)
    app.add_middleware(RateLimitMiddleware, max_requests=max_requests)
    app.add_middleware(CorrelationIdMiddleware)
    register_error_handlers(app)
    app.include_router(_router())
    app.dependency_overrides[get_settings] = lambda: settings
    return app


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "demo_key": DEMO_KEY,
        # These tests exercise the live-path gates, so fixture mode is off — which
        # means Settings requires an API key. A placeholder satisfies that; no
        # request in this module reaches the FortyGuard client.
        "fixture_mode": False,
        "fortyguard_api_key": "test-key-not-used",
        "app_env": "development",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# ═════════════════════════════════════════════════════════════════════════════
# Rate limiter
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def limited() -> Iterator[TestClient]:
    """Gate disabled (no demo key) so the limiter is what is being measured."""
    with TestClient(
        _app(_settings(demo_key=None), max_requests=3),
        raise_server_exceptions=False,
    ) as client:
        yield client


def test_requests_under_the_limit_pass(limited: TestClient) -> None:
    for _ in range(3):
        assert limited.post("/projects/p1/diagnose").status_code == 200


def test_request_over_the_limit_is_429(limited: TestClient) -> None:
    for _ in range(3):
        limited.post("/projects/p1/diagnose")

    response = limited.post("/projects/p1/diagnose")
    assert response.status_code == 429

    error = response.json()["error"]
    assert error["code"] == "RATE_LIMITED"
    # The client is told when to retry rather than left to guess.
    assert int(error["details"]["retryAfterSeconds"]) > 0


def test_reads_are_never_throttled(limited: TestClient) -> None:
    """A limit on GETs would make panning the map stutter."""
    for _ in range(30):
        assert limited.get("/projects/p1/tiles").status_code == 200


def test_ungated_posts_are_not_throttled(limited: TestClient) -> None:
    """Creating a project spends no credits, so it is not rate limited."""
    for _ in range(20):
        assert limited.post("/projects").status_code == 200


def test_the_limit_is_shared_across_costly_endpoints(limited: TestClient) -> None:
    """Budget protection is per-client, not per-path.

    Alternating between /diagnose and /plans must not double the allowance —
    both spend from the same credit balance.
    """
    limited.post("/projects/p1/diagnose")
    limited.post("/projects/p1/plans")
    limited.post("/projects/p1/diagnose")
    assert limited.post("/projects/p1/plans").status_code == 429


def test_clients_are_bucketed_separately(limited: TestClient) -> None:
    """One user exhausting their allowance must not lock out everyone else."""
    headers_a = {"X-Forwarded-For": "203.0.113.10"}
    headers_b = {"X-Forwarded-For": "203.0.113.99"}

    for _ in range(3):
        limited.post("/projects/p1/diagnose", headers=headers_a)
    assert limited.post("/projects/p1/diagnose", headers=headers_a).status_code == 429
    assert limited.post("/projects/p1/diagnose", headers=headers_b).status_code == 200


def test_rejection_still_carries_a_correlation_id(limited: TestClient) -> None:
    """Correlation is registered outermost so throttled requests stay traceable."""
    for _ in range(4):
        response = limited.post("/projects/p1/diagnose")
    assert response.status_code == 429
    assert response.json()["error"]["correlationId"]
    assert response.headers["X-Correlation-Id"]


# ═════════════════════════════════════════════════════════════════════════════
# Demo-key gate
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def gated() -> Iterator[TestClient]:
    with TestClient(
        _app(_settings(), max_requests=100), raise_server_exceptions=False
    ) as client:
        yield client


def test_correct_key_is_accepted(gated: TestClient) -> None:
    response = gated.post(
        "/projects/p1/diagnose", headers={HEADER_NAME: DEMO_KEY}
    )
    assert response.status_code == 200


def test_missing_key_is_401(gated: TestClient) -> None:
    response = gated.post("/projects/p1/diagnose")
    assert response.status_code == 401

    error = response.json()["error"]
    assert error["code"] == "UNAUTHORIZED"
    assert error["field"] == HEADER_NAME
    # The message tells the user where to find the key rather than just refusing.
    assert "readme" in str(error["message"]).lower()


@pytest.mark.parametrize(
    "wrong",
    ["", "wrong", DEMO_KEY + "x", DEMO_KEY[:-1], DEMO_KEY.upper(), " " + DEMO_KEY],
)
def test_incorrect_key_is_401(gated: TestClient, wrong: str) -> None:
    """Including near-misses: a prefix or a case change must not be accepted."""
    response = gated.post("/projects/p1/diagnose", headers={HEADER_NAME: wrong})
    assert response.status_code == 401


def test_reads_need_no_key(gated: TestClient) -> None:
    """Gating reads would break the fixture-mode demo, which needs no key at all."""
    assert gated.get("/projects/p1/tiles").status_code == 200


def test_ungated_post_needs_no_key(gated: TestClient) -> None:
    assert gated.post("/projects").status_code == 200


def test_every_credit_spending_endpoint_is_gated(gated: TestClient) -> None:
    for path in ("/projects/p1/diagnose", "/projects/p1/plans"):
        assert gated.post(path).status_code == 401, f"{path} is not gated"


def test_the_key_is_never_echoed_in_a_rejection(gated: TestClient) -> None:
    """A 401 body must not confirm any part of the expected value."""
    response = gated.post("/projects/p1/diagnose", headers={HEADER_NAME: "wrong"})
    assert DEMO_KEY not in response.text


def test_fixture_mode_needs_no_key() -> None:
    """Fixture mode spends nothing, so gating it would only obstruct the demo."""
    app = _app(_settings(fixture_mode=True), max_requests=100)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post("/projects/p1/diagnose").status_code == 200


def test_gate_is_off_when_no_key_is_configured() -> None:
    """Local development needs no setup.

    Safe because `Settings` refuses to start in production without a demo key, so
    this branch cannot silently disable the gate where it matters.
    """
    app = _app(_settings(demo_key=None), max_requests=100)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post("/projects/p1/diagnose").status_code == 200


def test_production_requires_a_demo_key() -> None:
    """The guarantee the permissive branch above depends on."""
    with pytest.raises(ValueError):
        Settings(
            app_env="production",
            demo_key=None,
            fixture_mode=True,
            cors_allowed_origins="https://example.com",
        )
