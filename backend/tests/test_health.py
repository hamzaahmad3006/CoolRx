"""Tests for the health and readiness endpoints.

The valuable assertion here is the negative one. With no database reachable the
app must report **not ready** with a 503, because a readiness probe that returns
200 while the intervention catalog is unverifiable would let an orchestrator send
traffic to an instance that cannot produce a cited number.

These tests run with no infrastructure on purpose — that *is* the scenario.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.config import get_settings
from routes import health


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A minimal app with only the health router.

    Deliberately not `main.app`: its lifespan runs the startup catalog gate,
    which is a different behaviour with its own test. Mounting the router alone
    isolates the endpoint contract.
    """
    app = FastAPI()
    app.include_router(health.router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client


def test_liveness_answers_even_without_a_database(client: TestClient) -> None:
    """Liveness must not depend on dependencies being up.

    A liveness probe that fails on a database outage gets the container killed
    and restarted, which fixes nothing and loses the logs.
    """
    response = client.get("/api/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["version"] == get_settings().app_version
    assert body["mode"] in {"live", "fixture"}


def test_liveness_reports_database_state_honestly(client: TestClient) -> None:
    """With no database running, the payload must say so rather than claim ok."""
    body = client.get("/api/health").json()
    assert body["dependencies"]["database"] == "down"
    assert body["status"] == "degraded"


def test_readiness_is_503_without_a_database(client: TestClient) -> None:
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["ready"] is False


def test_readiness_names_the_failing_checks(client: TestClient) -> None:
    """A failing probe must be diagnosable from its own response."""
    body = client.get("/api/health/ready").json()
    checks = {check["name"]: check for check in body["checks"]}

    assert checks["database"]["state"] == "down"
    assert checks["database"]["detail"]

    # PostGIS is only probed when the database is up — reporting it as "down"
    # here would misattribute the cause.
    assert "postgis" not in checks


def test_readiness_refuses_to_vouch_for_an_unverifiable_catalog(
    client: TestClient,
) -> None:
    """AC-23 at the probe level.

    The catalog check must fail closed. If it defaulted to "ok" when it could not
    be read, an instance with an empty catalog would be sent live traffic.
    """
    body = client.get("/api/health/ready").json()
    catalog = next(c for c in body["checks"] if c["name"] == "intervention_catalog")

    assert catalog["state"] == "down"
    assert catalog["detail"] is not None
    assert "database" in catalog["detail"].lower()


def test_readiness_reports_model_artifacts(client: TestClient) -> None:
    """Inference cannot run without model files, so it is a readiness concern."""
    body = client.get("/api/health/ready").json()
    names = {check["name"] for check in body["checks"]}
    assert "model_artifacts" in names


def test_readiness_check_states_are_within_the_declared_enum(
    client: TestClient,
) -> None:
    body = client.get("/api/health/ready").json()
    for check in body["checks"]:
        assert check["state"] in {"ok", "down", "skipped"}
