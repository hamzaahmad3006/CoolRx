"""Tests for response parsing and what a run admits to.

The parsing tests are written against the official API documentation at
docs-api.fortyguard.com, which confirms the completed payload as
`data.result.map_data` (a GeoJSON FeatureCollection of tile polygons) and
`data.result.stats_data.Temperature_stats` with capitalised Minimum / Maximum /
Mean / Standard_deviation.

Two of these tests exist because the pre-documentation implementation was wrong in
ways nothing would have surfaced until the API key arrived: it looked for a bare
array under `data`/`values`/`grid`, and it read `stats_data.mean` in lowercase.
Both would have produced an empty map and a null district mean, silently.

The one thing still undocumented is which property inside a feature holds the
value — `map_data` appears in the docs as an empty placeholder. So the parser tries
a candidate list and falls back to `None`, never to a guessed number.
"""

from __future__ import annotations

from typing import Any

import pytest

from clients.fortyguard.parsing import parse_heatmap, read_stat
from workers.pipeline import _degradation_reason
from workers.plan_pipeline import DEFAULT_QUANTITIES


def _feature(
    west: float, south: float, east: float, north: float, **properties: Any
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": properties,
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


def _result(*features: dict[str, Any], stats: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "map_data": {"type": "FeatureCollection", "features": list(features)},
        "stats_data": stats if stats is not None else {},
    }


# ═════════════════════════════════════════════════════════════════════════════
# map_data — the documented shape
# ═════════════════════════════════════════════════════════════════════════════


def test_tiles_come_from_the_geojson_feature_collection() -> None:
    parsed = parse_heatmap(
        _result(
            _feature(-112.10, 33.43, -112.09, 33.44, value=41.2),
            _feature(-112.09, 33.43, -112.08, 33.44, value=39.8),
        )
    )
    assert len(parsed.tiles) == 2
    assert [t.value for t in parsed.tiles] == [41.2, 39.8]
    assert parsed.value_key == "value"


def test_geometry_and_bounds_come_from_the_response() -> None:
    """The API's own tiles, not ours.

    Index-matching against a locally generated grid would mis-assign every
    temperature the moment their tiling differed from ours by one cell.
    """
    parsed = parse_heatmap(_result(_feature(-112.10, 33.43, -112.09, 33.44, value=41.2)))
    tile = parsed.tiles[0]
    assert (tile.west, tile.south, tile.east, tile.north) == (
        -112.10, 33.43, -112.09, 33.44,
    )
    assert tile.centroid_lon == pytest.approx(-112.095)
    assert tile.centroid_lat == pytest.approx(33.435)
    assert tile.geometry["type"] == "Polygon"


@pytest.mark.parametrize("key", ["value", "temperature", "tcm", "hours", "count"])
def test_known_value_property_names_are_read(key: str) -> None:
    parsed = parse_heatmap(_result(_feature(-1, 1, 0, 2, **{key: 12.5})))
    assert parsed.value_key == key
    assert parsed.tiles[0].value == 12.5


def test_an_unknown_value_property_yields_null_not_a_guess() -> None:
    """The rule the whole product rests on.

    An empty layer with a visible coverage figure is honest. A guessed one is a
    fabricated temperature field.
    """
    parsed = parse_heatmap(_result(_feature(-1, 1, 0, 2, mystery_reading=41.2)))
    assert parsed.value_key is None
    assert parsed.tiles[0].value is None
    # The tile itself is still recorded, so the map shows a no-data cell rather
    # than a hole.
    assert len(parsed.tiles) == 1


def test_the_value_key_is_decided_once_for_the_layer() -> None:
    """A single odd feature must not switch the key mid-layer and mix two
    quantities into one column."""
    parsed = parse_heatmap(
        _result(
            _feature(-1, 1, 0, 2, value=41.2),
            _feature(0, 1, 1, 2, hours=9),
        )
    )
    assert parsed.value_key == "value"
    assert parsed.tiles[0].value == 41.2
    assert parsed.tiles[1].value is None


def test_a_feature_missing_its_value_is_null_not_zero() -> None:
    parsed = parse_heatmap(
        _result(
            _feature(-1, 1, 0, 2, value=41.2),
            _feature(0, 1, 1, 2),
        )
    )
    assert parsed.tiles[1].value is None


def test_a_boolean_is_not_treated_as_a_number() -> None:
    """`True` is an int in Python; reading it as 1.0 °C would be a real reading."""
    parsed = parse_heatmap(_result(_feature(-1, 1, 0, 2, value=True)))
    assert parsed.tiles[0].value is None


def test_multipolygon_geometry_is_handled() -> None:
    result = _result()
    result["map_data"]["features"] = [
        {
            "type": "Feature",
            "properties": {"value": 30.0},
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [[[[-1, 1], [0, 1], [0, 2], [-1, 2], [-1, 1]]]],
            },
        }
    ]
    parsed = parse_heatmap(result)
    assert len(parsed.tiles) == 1
    assert parsed.tiles[0].west == -1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"map_data": None},
        {"map_data": {}},
        {"map_data": {"features": []}},
        {"map_data": {"features": "not-a-list"}},
    ],
)
def test_a_malformed_result_yields_no_tiles_rather_than_raising(
    payload: dict[str, Any],
) -> None:
    """A worker must reach a terminal state; a parser crash would fail the job
    with a traceback instead of a coverage figure."""
    assert parse_heatmap(payload).tiles == []


def test_coverage_counts_only_tiles_with_values() -> None:
    parsed = parse_heatmap(
        _result(
            _feature(-1, 1, 0, 2, value=41.2),
            _feature(0, 1, 1, 2),
            _feature(1, 1, 2, 2, value=38.0),
        )
    )
    assert len(parsed.tiles) == 3
    assert parsed.with_values == 2


# ═════════════════════════════════════════════════════════════════════════════
# stats_data — the documented, capitalised keys
# ═════════════════════════════════════════════════════════════════════════════


def test_stats_are_read_from_the_capitalised_temperature_stats_block() -> None:
    """The bug this replaces: the old reader looked for `stats_data.mean` and
    found nothing, producing a null district mean on every run."""
    stats = {
        "Temperature_stats": {
            "Minimum": 31.4,
            "Maximum": 47.9,
            "Mean": 41.2,
            "Standard_deviation": 2.8,
        }
    }
    result = _result(stats=stats)
    assert read_stat(result, "mean") == 41.2
    assert read_stat(result, "min") == 31.4
    assert read_stat(result, "max") == 47.9
    assert read_stat(result, "std") == 2.8


def test_a_flattened_stats_block_is_tolerated() -> None:
    result = _result(stats={"Mean": 40.0})
    assert read_stat(result, "mean") == 40.0


def test_a_missing_stat_is_none_not_zero() -> None:
    """A district mean of 0 °C would make every tile look extraordinarily hot."""
    assert read_stat(_result(), "mean") is None
    assert read_stat({}, "mean") is None
    assert read_stat(_result(stats={"Temperature_stats": {"Mean": "warm"}}), "mean") is None


def test_units_are_echoed_from_the_response() -> None:
    """Read, never assumed — the docs say tcm returns °C while exceedance,
    persistence and time_of_measure return hours (SRS C-4)."""
    assert parse_heatmap(_result(stats={"units": "hour"})).units == "hour"
    assert parse_heatmap(_result()).units is None


# ═════════════════════════════════════════════════════════════════════════════
# What a run admits to
# ═════════════════════════════════════════════════════════════════════════════


def test_a_complete_run_reports_nothing_missing() -> None:
    assert (
        _degradation_reason(
            enrichment_unavailable=[],
            attributed=500,
            tile_count=500,
            ladder_tiles=500,
            wanted_ladder=True,
        )
        is None
    )


def test_missing_land_cover_is_admitted() -> None:
    reason = _degradation_reason(
        enrichment_unavailable=["nlcd", "terrain"],
        attributed=500,
        tile_count=500,
        ladder_tiles=500,
        wanted_ladder=True,
    )
    assert reason is not None and "nlcd" in reason


def test_a_missing_model_is_admitted() -> None:
    reason = _degradation_reason(
        enrichment_unavailable=[],
        attributed=0,
        tile_count=500,
        ladder_tiles=500,
        wanted_ladder=True,
    )
    assert reason is not None and "not attributed" in reason


def test_an_entirely_missing_ladder_is_admitted() -> None:
    reason = _degradation_reason(
        enrichment_unavailable=[],
        attributed=500,
        tile_count=500,
        ladder_tiles=0,
        wanted_ladder=True,
    )
    assert reason is not None and "degrees" in reason


def test_a_ladder_that_was_not_requested_is_not_reported_missing() -> None:
    """Opting out is a choice, not a degradation."""
    assert (
        _degradation_reason(
            enrichment_unavailable=[],
            attributed=500,
            tile_count=500,
            ladder_tiles=0,
            wanted_ladder=False,
        )
        is None
    )


def test_several_problems_are_reported_together() -> None:
    reason = _degradation_reason(
        enrichment_unavailable=["nlcd"],
        attributed=0,
        tile_count=500,
        ladder_tiles=0,
        wanted_ladder=True,
    )
    assert reason is not None and reason.count(";") == 2


# ═════════════════════════════════════════════════════════════════════════════
# Planning conventions
# ═════════════════════════════════════════════════════════════════════════════


def test_every_catalog_unit_has_a_default_quantity() -> None:
    from repositories.catalog import VALID_UNITS

    assert VALID_UNITS <= set(DEFAULT_QUANTITIES)


def test_default_quantities_are_positive() -> None:
    assert all(value > 0 for value in DEFAULT_QUANTITIES.values())
