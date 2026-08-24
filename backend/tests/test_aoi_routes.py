"""End-to-end tests for the AOI pre-flight endpoint.

Runs over real HTTP with no database. `validate-aoi` touches no tables — that is the
point of it: the AOI Studio can validate on every drag of the size slider, so a user
learns their box is too large before a credit is ever spent.

The session dependency is overridden with a stub that fails loudly if touched, which
turns "this endpoint accidentally started querying" into a test failure rather than a
silent performance regression.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.config import get_settings
from middleware.correlation import CorrelationIdMiddleware
from middleware.errors import register_error_handlers
from repositories.base import get_session
from routes import projects


class _ForbiddenSession:
    """Any attribute access is a test failure.

    `validate-aoi` must not query. If it starts to, the AOI Studio's live badge
    becomes a database round-trip on every slider movement.
    """

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(
            f"validate-aoi touched the database (session.{name}); it must not"
        )


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_error_handlers(app)
    app.include_router(projects.router, prefix="/api")
    app.dependency_overrides[get_session] = lambda: _ForbiddenSession()

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _box(*, west: float, south: float, east: float, north: float) -> dict[str, object]:
    """A closed rectangular AOI. Positions are [lon, lat]."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [west, south],
                            [east, south],
                            [east, north],
                            [west, north],
                            [west, south],
                        ]
                    ],
                },
            }
        ],
    }


#: Central Phoenix, 2.99 mi² — comfortably inside the 10 mi² Basic-plan cap.
#: The exact span matters: 0.06° × 0.05° at this latitude is 11.94 mi² and would be
#: rejected, so the box is deliberately smaller than it looks.
PHOENIX = _box(west=-112.10, south=33.43, east=-112.07, north=33.455)

#: Downtown Toronto — inside the US coverage rectangles and known not to be
#: excludable geometrically (documented gap).
TORONTO = _box(west=-79.40, south=43.64, east=-79.38, north=43.66)


def test_valid_phoenix_aoi_is_accepted(client: TestClient) -> None:
    response = client.post("/api/projects/validate-aoi", json={"aoi": PHOENIX})
    assert response.status_code == 200

    body = response.json()
    assert body["isValid"] is True
    assert body["violations"] == []
    assert 0 < body["areaSqMi"] < 10


def test_response_is_camel_case(client: TestClient) -> None:
    """The frontend contract is camelCase throughout."""
    body = client.post("/api/projects/validate-aoi", json={"aoi": PHOENIX}).json()
    assert {"isValid", "areaSqMi", "maxAreaSqMi", "violations"} <= set(body)


def test_area_is_returned_even_when_invalid(client: TestClient) -> None:
    """The size badge needs a number while the user is still dragging the box."""
    huge = _box(west=-115.0, south=32.0, east=-110.0, north=36.0)
    body = client.post("/api/projects/validate-aoi", json={"aoi": huge}).json()

    assert body["isValid"] is False
    assert body["areaSqMi"] > 10, "the real area is reported, not clamped to the cap"
    assert body["maxAreaSqMi"] == get_settings().fg_max_aoi_sqmi


def test_oversized_aoi_names_the_area_violation(client: TestClient) -> None:
    huge = _box(west=-115.0, south=32.0, east=-110.0, north=36.0)
    body = client.post("/api/projects/validate-aoi", json={"aoi": huge}).json()

    codes = {violation["code"] for violation in body["violations"]}
    assert "AOI_AREA_EXCEEDED" in codes


def test_aoi_outside_us_coverage_is_rejected(client: TestClient) -> None:
    """London is outside every US rectangle, so it must be refused."""
    london = _box(west=-0.13, south=51.50, east=-0.09, north=51.52)
    body = client.post("/api/projects/validate-aoi", json={"aoi": london}).json()

    assert body["isValid"] is False
    codes = {violation["code"] for violation in body["violations"]}
    assert "AOI_OUTSIDE_COVERAGE" in codes


def test_toronto_passes_the_prefilter_as_documented(client: TestClient) -> None:
    """Records the known gap rather than leaving it as an untested assumption.

    Toronto sits south of the 49th parallel between the same meridians as Buffalo,
    so a rectangular filter cannot exclude it. This test exists so the limitation is
    visible in the suite; if it ever starts failing, the filter got better and the
    docs should be updated.
    """
    body = client.post("/api/projects/validate-aoi", json={"aoi": TORONTO}).json()
    coverage_codes = {
        v["code"] for v in body["violations"] if v["code"] == "AOI_OUTSIDE_COVERAGE"
    }
    assert coverage_codes == set(), (
        "Toronto is expected to pass the rectangular pre-filter — see the coverage "
        "warning in schemas/system.py"
    )


def test_credit_estimate_is_returned(client: TestClient) -> None:
    """The user sees the cost before committing to it."""
    body = client.post("/api/projects/validate-aoi", json={"aoi": PHOENIX}).json()
    # 3 base analytics + 11 ladder steps.
    assert body["estimatedCredits"] == 14


def test_unclosed_ring_is_a_422_envelope(client: TestClient) -> None:
    """Caught by the schema, and reported in the same envelope as everything else."""
    broken = _box(west=-112.10, south=33.43, east=-112.07, north=33.455)
    ring = broken["features"][0]["geometry"]["coordinates"][0]  # type: ignore[index]
    ring.pop()

    response = client.post("/api/projects/validate-aoi", json={"aoi": broken})
    assert response.status_code == 422

    error = response.json()["error"]
    assert error["code"] == "VALIDATION_FAILED"
    assert error["correlationId"]


def test_multi_feature_aoi_is_rejected(client: TestClient) -> None:
    """FortyGuard takes one bounding box, so two features are ambiguous."""
    two = _box(west=-112.10, south=33.43, east=-112.07, north=33.455)
    two["features"] = two["features"] * 2  # type: ignore[index,operator]

    assert (
        client.post("/api/projects/validate-aoi", json={"aoi": two}).status_code == 422
    )


def test_missing_body_is_a_422_envelope(client: TestClient) -> None:
    response = client.post("/api/projects/validate-aoi", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
