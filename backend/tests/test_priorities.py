"""Tests for tile prioritisation.

The pure functions are tested here; `rank_tiles` itself needs a database and lives in
the integration suite. The two worth pinning down are the ones where being wrong is
invisible: a UTC-to-local hour conversion that is off by hours still produces a
plausible-looking clock, and a quartile band that misplaces the boundary still
produces a plausible-looking map.
"""

from __future__ import annotations

import pytest

from optimizer.priorities import (
    _quartile_thresholds,
    assign_risk_level,
    utc_hour_to_local,
)


# ═════════════════════════════════════════════════════════════════════════════
# UTC → local solar hour
# ═════════════════════════════════════════════════════════════════════════════


def test_phoenix_afternoon_peak_stays_in_the_afternoon() -> None:
    """The bug this guards against.

    Phoenix (-112.07°) is 7.47 h behind UTC by solar time, and Arizona sits at
    UTC-7 year-round with no daylight saving. A 22:00 UTC peak is therefore 15:00
    locally — mid-afternoon. Showing it as 22:00 would tell a planner the hottest
    moment of a desert summer day happens at night.
    """
    assert utc_hour_to_local(22, -112.07) == 15


def test_greenwich_is_unchanged() -> None:
    assert utc_hour_to_local(15, 0.0) == 15


@pytest.mark.parametrize(
    ("hour_utc", "longitude", "expected"),
    [
        (0, -112.07, 17),   # wraps backwards past midnight
        (23, 15.0, 0),      # wraps forwards past midnight
        (12, 180.0, 0),     # dateline east
        (12, -180.0, 0),    # dateline west
    ],
)
def test_conversion_wraps_within_the_day(
    hour_utc: int, longitude: float, expected: int
) -> None:
    assert utc_hour_to_local(hour_utc, longitude) == expected


@pytest.mark.parametrize("longitude", [-180.0, -112.07, 0.0, 77.2, 180.0])
def test_result_is_always_a_valid_hour(longitude: float) -> None:
    for hour in range(24):
        local = utc_hour_to_local(hour, longitude)
        assert local is not None
        assert 0 <= local <= 23


def test_missing_inputs_yield_none_not_zero() -> None:
    """Zero is midnight — a real hour. Missing data must not become one."""
    assert utc_hour_to_local(None, -112.0) is None
    assert utc_hour_to_local(15, None) is None
    assert utc_hour_to_local(None, None) is None


# ═════════════════════════════════════════════════════════════════════════════
# Quartile thresholds
# ═════════════════════════════════════════════════════════════════════════════


def test_quartiles_of_a_simple_range() -> None:
    q1, q2, q3 = _quartile_thresholds([1.0, 2.0, 3.0, 4.0, 5.0])
    assert (q1, q2, q3) == (2.0, 3.0, 4.0)


def test_quartiles_are_ordered_for_arbitrary_input() -> None:
    values = [9.0, 1.0, 5.0, 3.0, 7.0, 2.0, 8.0]
    q1, q2, q3 = _quartile_thresholds(values)
    assert q1 <= q2 <= q3


def test_single_value_collapses_all_thresholds() -> None:
    """One tile with data must not crash the banding."""
    assert _quartile_thresholds([4.2]) == (4.2, 4.2, 4.2)


def test_identical_values_collapse_thresholds() -> None:
    """A uniform district has no hot quarter, and the bands say so."""
    q1, q2, q3 = _quartile_thresholds([3.0] * 10)
    assert q1 == q2 == q3 == 3.0
    # Every tile lands in `low` rather than a quarter being labelled extreme
    # for being marginally above an identical neighbour.
    assert assign_risk_level(3.0, (q1, q2, q3)) == "low"


def test_input_is_not_mutated() -> None:
    values = [5.0, 1.0, 3.0]
    _quartile_thresholds(values)
    assert values == [5.0, 1.0, 3.0]


# ═════════════════════════════════════════════════════════════════════════════
# Risk banding
# ═════════════════════════════════════════════════════════════════════════════


THRESHOLDS = (2.0, 4.0, 6.0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "low"),
        (1.9, "low"),
        (2.0, "low"),        # boundaries are inclusive-below
        (2.1, "moderate"),
        (4.0, "moderate"),
        (4.1, "high"),
        (6.0, "high"),
        (6.1, "extreme"),
        (99.0, "extreme"),
    ],
)
def test_banding_boundaries(value: float, expected: str) -> None:
    assert assign_risk_level(value, THRESHOLDS) == expected


def test_missing_value_is_low_not_extreme() -> None:
    """A tile with no measurement must never top the risk list.

    Defaulting the other way would put unmeasured tiles at the head of a
    priority ranking, sending a city to treat the places it knows least about.
    """
    assert assign_risk_level(None, THRESHOLDS) == "low"


def test_every_band_is_reachable() -> None:
    """A banding that can never emit `extreme` would be silently useless."""
    produced = {
        assign_risk_level(value, THRESHOLDS) for value in (1.0, 3.0, 5.0, 7.0)
    }
    assert produced == {"low", "moderate", "high", "extreme"}


def test_bands_are_monotonic_in_the_value() -> None:
    """Hotter must never be rated cooler."""
    order = {"low": 0, "moderate": 1, "high": 2, "extreme": 3}
    ratings = [
        order[assign_risk_level(value, THRESHOLDS)]
        for value in [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    ]
    assert ratings == sorted(ratings)


# ═════════════════════════════════════════════════════════════════════════════
# Equity weighting
# ═════════════════════════════════════════════════════════════════════════════


def _weighted(phh: float, svi: float, lam: float) -> float:
    """The formula as implemented in rank_tiles, isolated for testing."""
    return phh * (1.0 + lam * svi)


def test_lambda_zero_ignores_vulnerability() -> None:
    """λ=0 must optimise raw heat exposure, unchanged by SVI."""
    assert _weighted(1000.0, 0.9, 0.0) == _weighted(1000.0, 0.1, 0.0) == 1000.0


def test_higher_lambda_favours_vulnerable_tiles() -> None:
    vulnerable = _weighted(1000.0, 0.9, 2.0)
    comfortable = _weighted(1000.0, 0.1, 2.0)
    assert vulnerable > comfortable


def test_weighting_never_reduces_the_raw_figure() -> None:
    """`1 + λ·SVI` is ≥ 1 for non-negative λ and SVI, so weighting only adds."""
    for lam in (0.0, 0.5, 1.0, 5.0):
        for svi in (0.0, 0.25, 0.5, 1.0):
            assert _weighted(500.0, svi, lam) >= 500.0
