"""Water-distance provider tests. Offline — the NHD query is stubbed.

Verified live on 2026-08-21 over the Phoenix AOI: 144/144 tiles answered in 9.0 s
from 175 NHD features, 2,763.7-4,213.7 m to the nearest perennial water.

Cross-checked against the NLCD raster implementation this replaced, which
answered 2,690.1 m for the same ground — a 3% difference between two independent
sources measuring the same quantity. The raster took 185-729 s to do it, and on
an earlier attempt ran past twenty minutes without returning at all.

The two behaviours worth protecting:

* which NHD features count as water. Of 188 flowlines within 10 km of downtown
  Phoenix only four are perennial streams; the rest are canals, ephemeral washes,
  pipelines and routing lines. Counting a pipeline as a river, or a dry wash as a
  cooling feature, would put a wrong number into a model that predicts how much
  cooler a street gets.
* "no water found" is null rather than a large number.
"""

from __future__ import annotations

import pytest

from geo.grid import Tile
from geo.water import (
    PERENNIAL_FLOWLINE_FCODES,
    PERENNIAL_WATERBODY_FCODES,
    WaterDistanceProvider,
)

WEST, SOUTH, EAST, NORTH = -112.10, 33.44, -112.06, 33.47


def _tile(key: str, w: float, s: float, e: float, n: float) -> Tile:
    return Tile(
        tile_key=key, west=w, south=s, east=e, north=n,
        centroid_lon=(w + e) / 2, centroid_lat=(s + n) / 2,
    )


def _whole() -> Tile:
    return _tile("t", WEST, SOUTH, EAST, NORTH)


def _flowline(fcode: int, path: list[list[float]]) -> dict:
    return {"attributes": {"fcode": fcode}, "geometry": {"paths": [path]}}


def _waterbody(fcode: int, ring: list[list[float]]) -> dict:
    return {"attributes": {"FCODE": fcode}, "geometry": {"rings": [ring]}}


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def provider(monkeypatch):
    """Build a provider whose NHD layer queries return the given features.

    `flowlines` answers layer 6, `bodies` answers layer 10, matching the real
    service's split.
    """

    def _make(flowlines: list[dict] | None = None, bodies: list[dict] | None = None):
        p = WaterDistanceProvider()

        def _get(url, **kwargs):
            layer = url.rstrip("/").split("/")[-2]
            features = flowlines if layer == "6" else bodies
            return _Response({"features": list(features or [])})

        monkeypatch.setattr("geo._http.get", _get)
        return p

    return _make


# ── which features count as water ────────────────────────────────────────────

def test_a_perennial_stream_counts(provider) -> None:
    p = provider(flowlines=[_flowline(46006, [[-112.09, 33.44], [-112.09, 33.47]])])
    result = p.fetch([_whole()])
    assert result.values["t"]["dist_to_water_m"] is not None


def test_a_canal_counts(provider) -> None:
    """A judgement, not a fact: in an arid city the SRP canals are the dominant
    year-round open water. Recorded in provenance so a reviewer can disagree."""
    p = provider(flowlines=[_flowline(33600, [[-112.09, 33.44], [-112.09, 33.47]])])
    assert p.fetch([_whole()]).values["t"]["dist_to_water_m"] is not None


@pytest.mark.parametrize(
    ("fcode", "what"),
    [
        (46007, "ephemeral wash — bare sand for most of the cooling season"),
        (55800, "artificial path — a routing line, not itself water"),
        (42813, "pipeline — not open water"),
        (33400, "connector — a topological link"),
    ],
)
def test_non_water_flowlines_are_excluded(provider, fcode: int, what: str) -> None:
    """127 of 188 flowlines near downtown Phoenix are canals and 30 are routing
    lines. Taking every flowline would treat pipelines as rivers."""
    p = provider(flowlines=[_flowline(fcode, [[-112.09, 33.44], [-112.09, 33.47]])])
    result = p.fetch([_whole()])
    assert result.values["t"]["dist_to_water_m"] is None
    assert "10 km" in result.misses["t"]


def test_a_perennial_waterbody_counts(provider) -> None:
    ring = [[-112.09, 33.45], [-112.088, 33.45], [-112.088, 33.452],
            [-112.09, 33.452], [-112.09, 33.45]]
    p = provider(bodies=[_waterbody(39004, ring)])
    assert p.fetch([_whole()]).values["t"]["dist_to_water_m"] is not None


def test_an_intermittent_waterbody_is_excluded(provider) -> None:
    ring = [[-112.09, 33.45], [-112.088, 33.45], [-112.088, 33.452],
            [-112.09, 33.452], [-112.09, 33.45]]
    p = provider(bodies=[_waterbody(39001, ring)])
    assert p.fetch([_whole()]).values["t"]["dist_to_water_m"] is None


def test_the_fcode_sets_do_not_overlap() -> None:
    """Flowline and waterbody codes come from different NHD domains; an overlap
    would mean one of the two lists was copied from the wrong table."""
    assert not (PERENNIAL_FLOWLINE_FCODES & PERENNIAL_WATERBODY_FCODES)


# ── the measurement ──────────────────────────────────────────────────────────

def test_distance_grows_with_separation(provider) -> None:
    p = provider(flowlines=[_flowline(46006, [[-112.10, 33.44], [-112.10, 33.47]])])
    near = _tile("near", -112.098, 33.45, -112.094, 33.455)
    far = _tile("far", -112.070, 33.45, -112.066, 33.455)
    result = p.fetch([near, far])
    assert (
        result.values["far"]["dist_to_water_m"]
        > result.values["near"]["dist_to_water_m"]
    )


def test_distance_is_reported_in_metres_not_degrees(provider) -> None:
    """The AOI is ~3.7 km wide. Measured in degrees the far tile would read a
    fraction of one; in metres it must read thousands."""
    p = provider(flowlines=[_flowline(46006, [[-112.10, 33.44], [-112.10, 33.47]])])
    result = p.fetch([_tile("far", -112.070, 33.45, -112.066, 33.455)])
    assert result.values["far"]["dist_to_water_m"] > 1000.0


def test_the_nearest_of_several_features_wins(provider) -> None:
    far = _flowline(46006, [[-112.20, 33.44], [-112.20, 33.47]])
    near = _flowline(46006, [[-112.081, 33.44], [-112.081, 33.47]])

    # Each `provider(...)` call re-patches the shared HTTP seam, so every fetch
    # must happen while its own stub is the installed one.
    only_far = provider(flowlines=[far]).fetch([_whole()])
    both = provider(flowlines=[far, near]).fetch([_whole()])

    assert (
        both.values["t"]["dist_to_water_m"]
        < only_far.values["t"]["dist_to_water_m"]
    )


def test_a_tile_on_the_water_reads_about_zero(provider) -> None:
    p = provider(flowlines=[_flowline(46006, [[-112.08, 33.44], [-112.08, 33.47]])])
    result = p.fetch([_tile("on", -112.0805, 33.45, -112.0795, 33.451)])
    assert result.values["on"]["dist_to_water_m"] < 100.0


# ── absence and failure ──────────────────────────────────────────────────────

def test_no_water_in_the_window_answers_null_not_a_floor(provider) -> None:
    """Reporting the search radius as if it were a measurement would put a
    fabricated distance into a feature the model trains on."""
    p = provider()
    result = p.fetch([_whole()])
    assert result.values["t"]["dist_to_water_m"] is None
    assert "10 km" in result.misses["t"]


def test_a_transport_failure_yields_misses_rather_than_raising(monkeypatch) -> None:
    def _boom(*a, **k):
        raise ConnectionError("hydro.nationalmap.gov unreachable")

    monkeypatch.setattr("geo._http.get", _boom)
    result = WaterDistanceProvider().fetch([_whole()])
    assert result.values == {}
    assert result.misses["t"].startswith("water distance unavailable")


def test_an_arcgis_error_payload_is_a_miss_not_a_silent_empty(monkeypatch) -> None:
    """ArcGIS reports failure as a JSON error body with a 200. Parsed naively
    that looks like 'no features', which would read as 'no water nearby'."""
    monkeypatch.setattr(
        "geo._http.get",
        lambda url, **k: _Response({"error": {"code": 400, "message": "bad"}}),
    )
    result = WaterDistanceProvider().fetch([_whole()])
    assert result.values == {}
    assert result.misses["t"].startswith("water distance unavailable")


def test_malformed_geometry_is_skipped_not_fatal(provider) -> None:
    """One bad ring in a payload of hundreds must not lose the whole AOI."""
    good = _flowline(46006, [[-112.09, 33.44], [-112.09, 33.47]])
    bad = {"attributes": {"fcode": 46006}, "geometry": {"paths": [[[-112.0, 33.0]]]}}
    p = provider(flowlines=[bad, good])
    assert p.fetch([_whole()]).values["t"]["dist_to_water_m"] is not None


def test_an_empty_batch_makes_no_request(monkeypatch) -> None:
    monkeypatch.setattr(
        "geo._http.get",
        lambda *a, **k: pytest.fail("no request should be made for zero tiles"),
    )
    assert WaterDistanceProvider().fetch([]).values == {}


# ── provenance ───────────────────────────────────────────────────────────────

def test_provenance_names_the_source_and_the_radius() -> None:
    info = WaterDistanceProvider().info
    assert "National Hydrography Dataset" in info.source
    assert "10 km" in info.source


def test_provenance_records_the_canal_judgement() -> None:
    """Including canals is defensible in Phoenix and not everywhere. A reviewer
    must be able to see the choice rather than infer it from a constant."""
    source = WaterDistanceProvider().info.source
    assert "anal" in source
    assert "ephemeral" in source.lower()
