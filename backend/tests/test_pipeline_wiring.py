"""Tests for the pipeline's honesty logic.

The database-touching stages need a live PostgreSQL and live in the integration
suite. What is tested here is the reasoning that decides *what a run admits to* —
whether it reports success, degraded, or failure, and how it reads per-cell values
out of an upstream response whose shape is not fully documented.

Both matter more than they look. A run that reports success while its land-cover
column is entirely null puts a planner in front of a map that silently describes
nothing, and a response parser that guesses at an unrecognised shape invents the
values the whole product is built on.
"""

from __future__ import annotations

import pytest

from workers.pipeline import _degradation_reason, _stat, _values_by_index
from workers.plan_pipeline import DEFAULT_QUANTITIES


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
    """Otherwise the map silently describes nothing."""
    reason = _degradation_reason(
        enrichment_unavailable=["nlcd", "terrain"],
        attributed=500,
        tile_count=500,
        ladder_tiles=500,
        wanted_ladder=True,
    )
    assert reason is not None
    assert "nlcd" in reason and "terrain" in reason


def test_a_missing_model_is_admitted() -> None:
    reason = _degradation_reason(
        enrichment_unavailable=[],
        attributed=0,
        tile_count=500,
        ladder_tiles=500,
        wanted_ladder=True,
    )
    assert reason is not None
    assert "not attributed" in reason


def test_an_entirely_missing_ladder_is_admitted() -> None:
    """Without it, impact cannot leave degrees — which changes what the plan means."""
    reason = _degradation_reason(
        enrichment_unavailable=[],
        attributed=500,
        tile_count=500,
        ladder_tiles=0,
        wanted_ladder=True,
    )
    assert reason is not None
    assert "degrees" in reason


def test_a_mostly_missing_ladder_is_admitted_with_counts() -> None:
    reason = _degradation_reason(
        enrichment_unavailable=[],
        attributed=500,
        tile_count=500,
        ladder_tiles=100,
        wanted_ladder=True,
    )
    assert reason is not None
    assert "100 of 500" in reason


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
    """One at a time would have the user fix, re-run, and discover the next."""
    reason = _degradation_reason(
        enrichment_unavailable=["nlcd"],
        attributed=0,
        tile_count=500,
        ladder_tiles=0,
        wanted_ladder=True,
    )
    assert reason is not None
    assert reason.count(";") == 2


# ═════════════════════════════════════════════════════════════════════════════
# Reading the upstream response
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("key", ["data", "values", "grid", "cells", "heatmap"])
def test_a_bare_number_list_is_read(key: str) -> None:
    """The response container is not documented, so several are accepted."""
    values = _values_by_index({key: [41.2, 39.8, 44.0]})
    assert values == {0: 41.2, 1: 39.8, 2: 44.0}


@pytest.mark.parametrize("field", ["value", "temperature", "tcm", "hours"])
def test_a_list_of_objects_is_read(field: str) -> None:
    values = _values_by_index({"data": [{field: 41.2}, {field: 39.8}]})
    assert values == {0: 41.2, 1: 39.8}


def test_cells_without_a_value_are_absent_not_zero() -> None:
    """A cell the API had no reading for must not become a measurement of zero."""
    values = _values_by_index({"data": [{"value": 41.2}, {"note": "no data"}, {"value": 39.0}]})
    assert values == {0: 41.2, 2: 39.0}
    assert 1 not in values


def test_an_unrecognised_shape_yields_nothing_rather_than_a_guess() -> None:
    """The rule the whole product rests on.

    An empty layer with a visible coverage figure is honest. A guessed one is a
    fabricated temperature field.
    """
    assert _values_by_index({"unexpected": {"nested": [1, 2, 3]}}) == {}
    assert _values_by_index({}) == {}


def test_an_empty_list_yields_nothing() -> None:
    assert _values_by_index({"data": []}) == {}


def test_non_numeric_entries_are_skipped() -> None:
    values = _values_by_index({"data": [41.2, "n/a", None, 39.0]})
    assert values == {0: 41.2, 3: 39.0}


# ═════════════════════════════════════════════════════════════════════════════
# Stats
# ═════════════════════════════════════════════════════════════════════════════


def test_a_stat_is_read_from_the_response() -> None:
    assert _stat({"stats_data": {"mean": 41.2}}, "mean") == 41.2


def test_a_missing_stat_is_none_not_zero() -> None:
    """A district mean of 0 °C would make every tile look extraordinarily hot."""
    assert _stat({"stats_data": {}}, "mean") is None
    assert _stat({}, "mean") is None
    assert _stat({"stats_data": {"mean": "warm"}}, "mean") is None


# ═════════════════════════════════════════════════════════════════════════════
# Planning conventions
# ═════════════════════════════════════════════════════════════════════════════


def test_every_catalog_unit_has_a_default_quantity() -> None:
    """A unit with no quantity would silently apply one unit per block.

    That is a planning decision, and it must be declared rather than defaulted.
    """
    from repositories.catalog import VALID_UNITS

    assert VALID_UNITS <= set(DEFAULT_QUANTITIES)


def test_default_quantities_are_positive() -> None:
    assert all(value > 0 for value in DEFAULT_QUANTITIES.values())
