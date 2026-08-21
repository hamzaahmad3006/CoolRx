"""Building-footprint provider tests. Offline — Overpass is stubbed.

Unlike every other provider here, this one has **not** been verified against a live
Overpass response: the main instance returned 504 and the Kumi mirror 502 for the
`out geom;` query on 2026-08-21. These tests cover the parsing, the coverage maths
and the failure behaviour; they cannot prove the query shape is right.

One thing that *was* learned live and is asserted below: Overpass rejects the default
`python-httpx` user agent with 406 before parsing the query at all.
"""

from __future__ import annotations

import pytest

from geo.buildings import BuildingFootprintProvider, _USER_AGENT
from geo.grid import Tile

WEST, SOUTH, EAST, NORTH = -112.080, 33.448, -112.076, 33.452


def _tile(key: str, w: float, s: float, e: float, n: float) -> Tile:
    return Tile(
        tile_key=key, west=w, south=s, east=e, north=n,
        centroid_lon=(w + e) / 2, centroid_lat=(s + n) / 2,
    )


def _square(w: float, s: float, e: float, n: float):
    from shapely.geometry import Polygon
    return Polygon([(w, s), (e, s), (e, n), (w, n), (w, s)])


@pytest.fixture
def provider(monkeypatch):
    def _make(footprints):
        p = BuildingFootprintProvider()
        monkeypatch.setattr(p, "_footprints", lambda *a, **k: footprints)
        return p
    return _make


def _whole() -> Tile:
    return _tile("t", WEST, SOUTH, EAST, NORTH)


def test_a_footprint_covering_the_whole_tile_reads_one_hundred(provider):
    p = provider([_square(WEST, SOUTH, EAST, NORTH)])
    result = p.fetch([_whole()])
    assert result.values["t"]["building_pct"] == pytest.approx(100.0, abs=0.1)


def test_a_quarter_covered_tile_reads_twenty_five(provider):
    mid_x = (WEST + EAST) / 2
    mid_y = (SOUTH + NORTH) / 2
    p = provider([_square(WEST, SOUTH, mid_x, mid_y)])
    result = p.fetch([_whole()])
    assert result.values["t"]["building_pct"] == pytest.approx(25.0, abs=0.5)


def test_overlapping_footprints_cannot_exceed_one_hundred(provider):
    """OSM footprints do overlap. Summing intersections can exceed the tile, and
    '118% built' is not a thing."""
    whole = _square(WEST, SOUTH, EAST, NORTH)
    p = provider([whole, whole, whole])
    result = p.fetch([_whole()])
    assert result.values["t"]["building_pct"] == 100.0


def test_a_tile_with_no_footprints_over_it_reads_zero(provider):
    """Zero here is a measurement: the query succeeded and found buildings in the
    AOI, just not on this tile."""
    elsewhere = _square(-112.070, 33.460, -112.069, 33.461)
    p = provider([elsewhere])
    result = p.fetch([_whole()])
    assert result.values["t"]["building_pct"] == 0.0


def test_an_aoi_with_nothing_mapped_answers_null_not_zero(provider):
    """A whole district with no mapped buildings is far more likely unsurveyed
    than empty, and reporting 0% built for it would be a claim about the ground."""
    p = provider([])
    result = p.fetch([_whole()])
    assert result.values["t"]["building_pct"] is None
    assert "unmapped" in result.misses["t"]


def test_a_transport_failure_yields_misses_rather_than_raising(monkeypatch):
    p = BuildingFootprintProvider()

    def _boom(*a, **k):
        raise ConnectionError("overpass unreachable")

    monkeypatch.setattr(p, "_footprints", _boom)
    result = p.fetch([_whole()])
    assert result.values == {}
    assert result.misses["t"].startswith("buildings unavailable")


def test_an_empty_batch_makes_no_request(monkeypatch):
    p = BuildingFootprintProvider()
    monkeypatch.setattr(
        p, "_footprints",
        lambda *a, **k: pytest.fail("no request should be made for zero tiles"),
    )
    assert p.fetch([]).values == {}


# ── things learned from the live service ─────────────────────────────────────

def test_a_user_agent_is_sent(monkeypatch):
    """Overpass answers 406 Not Acceptable to the default python-httpx agent,
    before it even parses the query — so the failure looks like a malformed
    request rather than a blocked client. Their usage policy also asks callers to
    identify themselves."""
    captured: dict = {}

    class _Response:
        status_code = 200
        def raise_for_status(self): return None
        def json(self): return {"elements": []}

    def _post(method, url, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr("httpx.request", _post)
    BuildingFootprintProvider()._footprints(WEST, SOUTH, EAST, NORTH)

    assert captured["headers"]["User-Agent"] == _USER_AGENT
    assert "CoolRx" in _USER_AGENT


def test_malformed_geometry_is_skipped_not_fatal(monkeypatch):
    """One bad way in a payload of thousands must not lose the whole AOI."""
    class _Response:
        status_code = 200
        def raise_for_status(self): return None
        def json(self):
            return {"elements": [
                {"geometry": [{"lon": 0, "lat": 0}]},                    # too few points
                {"geometry": []},                                        # empty
                {},                                                      # no geometry
                {"geometry": [                                           # valid
                    {"lon": WEST, "lat": SOUTH}, {"lon": EAST, "lat": SOUTH},
                    {"lon": EAST, "lat": NORTH}, {"lon": WEST, "lat": NORTH},
                    {"lon": WEST, "lat": SOUTH},
                ]},
            ]}

    monkeypatch.setattr("httpx.request", lambda *a, **k: _Response())
    footprints = BuildingFootprintProvider()._footprints(WEST, SOUTH, EAST, NORTH)
    assert len(footprints) == 1


def test_provenance_carries_the_odbl_attribution() -> None:
    """The only source here with a licence that obliges anything."""
    info = BuildingFootprintProvider().info
    assert "OpenStreetMap contributors" in info.source
    assert "ODbL" in info.source
    assert info.resolution_m is None
