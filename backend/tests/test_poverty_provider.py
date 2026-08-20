"""Poverty provider tests.

Offline — both upstreams are stubbed. Verified live against the Phoenix AOI on
2026-08-20: rates of 18.4% to 37.6% across four tiles, with tract 1131's own figure
(1,885 of 5,011 = 37.6%) landing exactly on the tile that sits wholly inside it.

The behaviour worth protecting here is that a **rate is not a count**. Population is
apportioned; a poverty rate is assigned. Getting that wrong would quietly dilute
every equity figure in the product.
"""

from __future__ import annotations

import pytest

from geo.grid import Tile
from geo.poverty import PovertyProvider, _number

TRACT_WEST, TRACT_SOUTH, TRACT_EAST, TRACT_NORTH = -112.08, 33.44, -112.07, 33.45


def _tile(key: str, w: float, s: float, e: float, n: float) -> Tile:
    return Tile(
        tile_key=key, west=w, south=s, east=e, north=n,
        centroid_lon=(w + e) / 2, centroid_lat=(s + n) / 2,
    )


def _bg(geoid: str, w: float, s: float, e: float, n: float) -> dict:
    """A block group; its tract is the GEOID's first 11 characters."""
    return {
        "properties": {
            "GEOID": geoid, "STATE": geoid[:2],
            "COUNTY": geoid[2:5], "TRACT": geoid[5:11], "BLKGRP": geoid[11:],
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
        },
    }


@pytest.fixture
def provider(monkeypatch):
    def _make(groups, rates):
        p = PovertyProvider(api_key="test-key")
        monkeypatch.setattr(p, "_block_groups", lambda *a, **k: groups)
        monkeypatch.setattr(p, "_poverty_rates", lambda *a, **k: rates)
        return p
    return _make


# ── a rate is not a count ────────────────────────────────────────────────────

def test_a_tile_covering_part_of_a_tract_gets_the_whole_rate(provider):
    """37.6% poverty over a tract does not become 11% because a tile covers 30%
    of it. The tile's residents are still drawn from that population."""
    p = provider(
        [_bg("040131131001", TRACT_WEST, TRACT_SOUTH, TRACT_EAST, TRACT_NORTH)],
        {"04013113100": 0.376},
    )
    small = _tile(
        "t", TRACT_WEST, TRACT_SOUTH,
        TRACT_WEST + (TRACT_EAST - TRACT_WEST) * 0.3, TRACT_NORTH,
    )
    result = p.fetch([small])
    assert result.values["t"]["pct_poverty"] == pytest.approx(0.376)


def test_a_tile_straddling_two_tracts_gets_a_weighted_mix(provider):
    """Half in a 10% tract and half in a 50% one is 30% — a mix of the two
    rates, not a dilution of either."""
    mid = (TRACT_WEST + TRACT_EAST) / 2
    groups = [
        _bg("040131131001", TRACT_WEST, TRACT_SOUTH, mid, TRACT_NORTH),
        _bg("040131141001", mid, TRACT_SOUTH, TRACT_EAST, TRACT_NORTH),
    ]
    rates = {"04013113100": 0.10, "04013114100": 0.50}
    p = provider(groups, rates)
    result = p.fetch(
        [_tile("t", TRACT_WEST, TRACT_SOUTH, TRACT_EAST, TRACT_NORTH)]
    )
    assert result.values["t"]["pct_poverty"] == pytest.approx(0.30, abs=0.01)


def test_the_mix_follows_overlap_not_tract_count(provider):
    """Three quarters inside the 10% tract should land near 20%, not 30%."""
    split = TRACT_WEST + (TRACT_EAST - TRACT_WEST) * 0.75
    groups = [
        _bg("040131131001", TRACT_WEST, TRACT_SOUTH, split, TRACT_NORTH),
        _bg("040131141001", split, TRACT_SOUTH, TRACT_EAST, TRACT_NORTH),
    ]
    rates = {"04013113100": 0.10, "04013114100": 0.50}
    p = provider(groups, rates)
    result = p.fetch(
        [_tile("t", TRACT_WEST, TRACT_SOUTH, TRACT_EAST, TRACT_NORTH)]
    )
    assert result.values["t"]["pct_poverty"] == pytest.approx(0.20, abs=0.02)


def test_a_tile_outside_every_tract_answers_null(provider):
    p = provider(
        [_bg("040131131001", TRACT_WEST, TRACT_SOUTH, TRACT_EAST, TRACT_NORTH)],
        {"04013113100": 0.376},
    )
    result = p.fetch([_tile("far", -80.0, 25.0, -79.99, 25.01)])
    assert result.values["far"]["pct_poverty"] is None
    assert result.misses["far"]


def test_a_tract_with_no_rate_is_skipped_not_zeroed(provider):
    """ACS publishes no rate for some tracts. Zero would assert nobody there is
    poor, which is a claim the data does not make."""
    # A rate exists for some other tract, so this is a genuine per-tract gap
    # rather than the upstream returning nothing at all.
    p = provider(
        [_bg("040131131001", TRACT_WEST, TRACT_SOUTH, TRACT_EAST, TRACT_NORTH)],
        {"04013999900": 0.21},
    )
    result = p.fetch(
        [_tile("t", TRACT_WEST, TRACT_SOUTH, TRACT_EAST, TRACT_NORTH)]
    )
    assert result.values["t"]["pct_poverty"] is None
    assert result.misses["t"]


# ── ACS parsing ──────────────────────────────────────────────────────────────

def test_null_and_annotation_codes_are_not_values():
    assert _number(None) is None
    assert _number("-666666666") is None
    assert _number("1885") == 1885.0


def test_a_zero_universe_produces_no_rate(monkeypatch):
    """Universe zero means nobody had poverty status determined — not 0% poverty.
    Dividing would be a ZeroDivisionError; reporting 0.0 would be a lie."""
    p = PovertyProvider(api_key="test-key")

    class _Response:
        status_code = 200
        def raise_for_status(self): return None
        def json(self):
            return [
                ["B17001_001E", "B17001_002E", "state", "county", "tract"],
                ["0", "0", "04", "013", "113100"],
            ]

    monkeypatch.setattr("httpx.get", lambda *a, **k: _Response())
    rates = p._poverty_rates(
        [_bg("040131131001", TRACT_WEST, TRACT_SOUTH, TRACT_EAST, TRACT_NORTH)]
    )
    assert rates == {}


# ── availability and failure ─────────────────────────────────────────────────

def test_without_a_key_the_provider_reports_unavailable():
    p = PovertyProvider(api_key=None)
    assert p.is_available() is False
    result = p.fetch([_tile("a", TRACT_WEST, TRACT_SOUTH, TRACT_EAST, TRACT_NORTH)])
    assert "CENSUS_API_KEY" in result.misses["a"]


def test_a_transport_failure_yields_misses_rather_than_raising(monkeypatch):
    p = PovertyProvider(api_key="test-key")

    def _boom(*a, **k):
        raise ConnectionError("tigerweb unreachable")

    monkeypatch.setattr(p, "_block_groups", _boom)
    result = p.fetch([_tile("a", TRACT_WEST, TRACT_SOUTH, TRACT_EAST, TRACT_NORTH)])
    assert result.values == {}
    assert result.misses["a"].startswith("poverty unavailable")


def test_an_empty_batch_makes_no_request(monkeypatch):
    p = PovertyProvider(api_key="test-key")
    monkeypatch.setattr(
        p, "_block_groups",
        lambda *a, **k: pytest.fail("no request should be made for zero tiles"),
    )
    assert p.fetch([]).values == {}


def test_the_provenance_declares_tract_resolution() -> None:
    """The Methods page reproduces this. A tract figure must never read as
    tile-level precision — the same rule the SRS applies to SVI."""
    info = PovertyProvider(api_key="k").info
    assert info.resolution_m is None
    assert "TRACT" in info.source
    assert "coarser than a tile" in info.source
