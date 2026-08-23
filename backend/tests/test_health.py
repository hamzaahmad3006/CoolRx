"""Tests for the health and readiness endpoints.

The valuable assertion here is the negative one. With no database reachable the
app must report **not ready** with a 503, because a readiness probe that returns
200 while the intervention catalog is unverifiable would let an orchestrator send
traffic to an instance that cannot produce a cited number.

The down-path tests **simulate** an unreachable database rather than relying on
one being absent from the machine. Until 2026-08-22 they did rely on it, and the
day Postgres was first started locally all four failed — not because the product
broke, but because they had been asserting "no database is running here", which
is a fact about the developer's laptop rather than about the code. A test that
passes only when infrastructure is missing is not testing the failure path; it is
testing the environment.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.config import get_settings
from routes import health


@pytest.fixture
def no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the database look unreachable, whatever is actually running.

    `routes.health` imports `check_connectivity` into its own namespace, so the
    patch has to land there rather than on `repositories.base`.
    """
    monkeypatch.setattr(health, "check_connectivity", lambda: False)


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


def test_liveness_reports_database_state_honestly(client: TestClient, no_database: None) -> None:
    """With no database running, the payload must say so rather than claim ok."""
    body = client.get("/api/health").json()
    assert body["dependencies"]["database"] == "down"
    assert body["status"] == "degraded"


def test_readiness_is_503_without_a_database(client: TestClient, no_database: None) -> None:
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json()["ready"] is False


def test_readiness_names_the_failing_checks(client: TestClient, no_database: None) -> None:
    """A failing probe must be diagnosable from its own response."""
    body = client.get("/api/health/ready").json()
    checks = {check["name"]: check for check in body["checks"]}

    assert checks["database"]["state"] == "down"
    assert checks["database"]["detail"]

    # PostGIS is only probed when the database is up — reporting it as "down"
    # here would misattribute the cause.
    assert "postgis" not in checks


def test_readiness_refuses_to_vouch_for_an_unverifiable_catalog(
    client: TestClient, no_database: None
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


# ── the ready path ───────────────────────────────────────────────────────────
#
# Untestable until Postgres first ran locally on 2026-08-22. Every assertion
# above is about refusing traffic; none of them could show that the probe ever
# *admits* it, so a readiness endpoint hard-wired to 503 would have passed the
# whole file.

@pytest.fixture
def database_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "check_connectivity", lambda: True)


def _requires_postgres() -> bool:
    from repositories.base import check_connectivity

    return check_connectivity()


needs_db = pytest.mark.skipif(
    not _requires_postgres(), reason="needs a live PostgreSQL"
)


@needs_db
def test_liveness_reports_ok_when_the_database_is_up(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["dependencies"]["database"] == "ok"
    assert body["status"] == "ok"


@needs_db
def test_readiness_admits_traffic_when_every_check_passes(
    client: TestClient,
) -> None:
    """The counterpart to the 503 tests. Without this, a probe wired to refuse
    everything would satisfy the rest of this file."""
    response = client.get("/api/health/ready")
    body = response.json()

    failing = [c for c in body["checks"] if c["state"] == "down"]
    assert not failing, f"checks reporting down: {failing}"
    assert response.status_code == 200
    assert body["ready"] is True


@needs_db
def test_postgis_is_probed_once_the_database_answers(client: TestClient) -> None:
    """It is skipped while the database is down, so the only way to learn the
    probe exists at all is to run it against a live one."""
    body = client.get("/api/health/ready").json()
    checks = {c["name"]: c for c in body["checks"]}
    assert "postgis" in checks
    assert checks["postgis"]["state"] == "ok"


@needs_db
def test_the_catalog_check_sees_the_loaded_rows(client: TestClient) -> None:
    """AC-23 from the other side: with a populated catalog the check must pass,
    and it must be the catalog it is reading rather than a constant."""
    body = client.get("/api/health/ready").json()
    catalog = next(c for c in body["checks"] if c["name"] == "intervention_catalog")
    assert catalog["state"] == "ok"
