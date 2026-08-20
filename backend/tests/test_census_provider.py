"""Census exposure provider tests.

Offline by construction — `conftest.py` pins the suite off the network, and these
stub both upstreams. What is exercised is the part that can be wrong: areal
apportionment, ACS's several ways of saying "no value", and failure behaviour.

Verified live against the Phoenix AOI on 2026-08-19 (three block groups holding
1,929 / 2,026 / 2,654 people; four tiles received 61.5-144.8 each). That cannot be
asserted here without calling the API on every test run.
"""

from __future__ import annotations

import pytest

from geo.census import CensusExposureProvider, _number
from geo.grid import Tile

# One square block group, 0.01 deg on a side.
BG_WEST, BG_SOUTH, BG_EAST, BG_NORTH = -112.08, 33.44, -112.07, 33.45


def _tile(key: str, w: float, s: float, e: float, n: float) -> Tile:
    return Tile(
        tile_key=key, west=w, south=s, east=e, north=n,
        centroid_lon=(w + e) / 2, centroid_lat=(s + n) / 2,
    )


def _square(geoid: str, w: float, s: float, e: float, n: float) -> dict:
    return {
        "properties": {
            "GEOID": geoid, "STATE": "04", "COUNTY": "013",
            "TRACT": "113100", "BLKGRP": geoid[-1],
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
        },
    }


@pytest.fixture
def provider(monkeypatch):
    """A provider whose two upstreams are supplied rather than fetched."""
    def _make(groups, attributes):
        p = CensusExposureProvider(api_key="test-key")
        monkeypatch.setattr(p, "_block_groups", lambda *a, **k: groups)
        monkeypatch.setattr(p, "_acs_attributes", lambda *a, **k: attributes)
        return p
    return _make


# ── apportionment ────────────────────────────────────────────────────────────

def test_a_tile_covering_the_whole_block_group_receives_all_its_people(provider):
    p = provider(
        [_square("040131131001", BG_WEST, BG_SOUTH, BG_EAST, BG_NORTH)],
        {"040131131001": {"population": 1000.0, "pct_over65": 0.10}},
    )
    result = p.fetch([_tile("t", BG_WEST, BG_SOUTH, BG_EAST, BG_NORTH)])
    assert result.values["t"]["population"] == pytest.approx(1000.0, rel=1e-6)


def test_a_tile_covering_half_receives_half(provider):
    """Areal share is the whole method: 50% of the area, 50% of the people."""
    mid = (BG_WEST + BG_EAST) / 2
    p = provider(
        [_square("040131131001", BG_WEST, BG_SOUTH, BG_EAST, BG_NORTH)],
        {"040131131001": {"population": 1000.0, "pct_over65": 0.10}},
    )
    result = p.fetch([_tile("t", BG_WEST, BG_SOUTH, mid, BG_NORTH)])
    assert result.values["t"]["population"] == pytest.approx(500.0, rel=1e-3)


def test_apportionment_conserves_the_block_group_total(provider):
    """AC-04: tile populations must sum to the block-group total.

    Conservation is what makes the estimate defensible — inventing or losing
    people between geographies would make every downstream impact figure wrong.
    """
    mid_x = (BG_WEST + BG_EAST) / 2
    mid_y = (BG_SOUTH + BG_NORTH) / 2
    quadrants = [
        _tile("q1", BG_WEST, BG_SOUTH, mid_x, mid_y),
        _tile("q2", mid_x, BG_SOUTH, BG_EAST, mid_y),
        _tile("q3", BG_WEST, mid_y, mid_x, BG_NORTH),
        _tile("q4", mid_x, mid_y, BG_EAST, BG_NORTH),
    ]
    p = provider(
        [_square("040131131001", BG_WEST, BG_SOUTH, BG_EAST, BG_NORTH)],
        {"040131131001": {"population": 2000.0, "pct_over65": 0.2}},
    )
    result = p.fetch(quadrants)
    total = sum(v["population"] for v in result.values.values())
    assert total == pytest.approx(2000.0, rel=0.01)


def test_pct_over65_is_population_weighted_across_two_block_groups(provider):
    """A tile straddling two block groups gets the mix its people come from.

    A flat average would let a nearly-empty block group pull the rate as hard as
    a dense one.
    """
    mid = (BG_WEST + BG_EAST) / 2
    groups = [
        _square("040131131001", BG_WEST, BG_SOUTH, mid, BG_NORTH),
        _square("040131131002", mid, BG_SOUTH, BG_EAST, BG_NORTH),
    ]
    attributes = {
        "040131131001": {"population": 900.0, "pct_over65": 0.10},
        "040131131002": {"population": 100.0, "pct_over65": 0.50},
    }
    p = provider(groups, attributes)
    result = p.fetch([_tile("t", BG_WEST, BG_SOUTH, BG_EAST, BG_NORTH)])

    # 900 people at 10% and 100 at 50% → 140/1000 = 0.14, not the flat mean 0.30.
    assert result.values["t"]["pct_over65"] == pytest.approx(0.14, abs=0.01)


def test_a_tile_touching_no_block_group_answers_null(provider):
    p = provider(
        [_square("040131131001", BG_WEST, BG_SOUTH, BG_EAST, BG_NORTH)],
        {"040131131001": {"population": 1000.0, "pct_over65": 0.1}},
    )
    result = p.fetch([_tile("far", -80.0, 25.0, -79.99, 25.01)])
    assert result.values["far"]["population"] is None
    assert result.misses["far"]


# ── ACS's several ways of saying "no value" ──────────────────────────────────

def test_a_null_from_acs_is_none_not_zero():
    """ACS returns null where a figure is not published at that geography —
    B17001 at block group, for instance. Zero would assert nobody is in poverty."""
    assert _number(None) is None


def test_acs_annotation_codes_are_discarded():
    """-666666666 and friends are annotations, not measurements."""
    assert _number("-666666666") is None
    assert _number("-999999999") is None


def test_ordinary_values_parse():
    assert _number("1929") == 1929.0
    assert _number("0") == 0.0
    assert _number("not-a-number") is None


# ── availability and failure ─────────────────────────────────────────────────

def test_without_a_key_the_provider_reports_unavailable_once():
    """Reported up front rather than as one miss per tile, so the pipeline can
    say 'no census key' instead of implying the data is genuinely sparse."""
    p = CensusExposureProvider(api_key=None)
    assert p.is_available() is False

    tiles = [_tile("a", BG_WEST, BG_SOUTH, BG_EAST, BG_NORTH)]
    result = p.fetch(tiles)
    assert result.values == {}
    assert "CENSUS_API_KEY" in result.misses["a"]


def test_a_transport_failure_yields_misses_rather_than_raising(monkeypatch):
    p = CensusExposureProvider(api_key="test-key")

    def _boom(*args, **kwargs):
        raise ConnectionError("tigerweb unreachable")

    monkeypatch.setattr(p, "_block_groups", _boom)
    result = p.fetch([_tile("a", BG_WEST, BG_SOUTH, BG_EAST, BG_NORTH)])
    assert result.values == {}
    assert result.misses["a"].startswith("census exposure unavailable")


def test_an_empty_batch_makes_no_request(monkeypatch):
    p = CensusExposureProvider(api_key="test-key")
    monkeypatch.setattr(
        p, "_block_groups",
        lambda *a, **k: pytest.fail("no request should be made for zero tiles"),
    )
    assert p.fetch([]).values == {}


def test_the_provider_declares_no_single_resolution():
    """Block groups vary from a city block to a county. Declaring a cell size
    would imply a precision the source does not have."""
    p = CensusExposureProvider(api_key="test-key")
    assert p.info.resolution_m is None
    assert p.fields == ("population", "pct_over65")
    assert "ACS" in p.info.source
