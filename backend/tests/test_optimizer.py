"""Tests for the exceedance ladder and plan selection.

The catalog values used here are invented, and that is fine: they never leave the
test process. The rule against unsourced numbers governs what reaches a user, not
what a fixture feeds an algorithm.

The properties under test are the ones that would produce a *plausible wrong plan*
rather than a crash: a budget quietly exceeded, hours avoided extrapolated past
what the API measured, two treatments stacked on one block, or a district-wide mean
that reports the treated-tile average.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from optimizer.counterfactual import (
    CatalogDeltaEstimator,
    DeltaEstimate,
    TileContext,
    check_feasibility,
    clamp_to_catalog,
)
from optimizer.ladder import (
    MAX_EVALUABLE_DELTA_C,
    LadderError,
    TileLadder,
    build_ladder,
    equity_weighted,
    person_heat_hours,
)
from optimizer.select import (
    Candidate,
    build_candidates,
    mean_delta_over_aoi,
    objective_benefit,
    select_plan,
)


@dataclass(frozen=True, slots=True)
class FakeEntry:
    code: str
    category: str = "green"
    unit: str = "tree"
    unit_cost_usd: Decimal = Decimal("450.00")
    delta_c_low: Decimal = Decimal("-2.50")
    delta_c_high: Decimal = Decimal("-0.40")
    feasibility_rule: Any = None


def _ladder(*hours: float, base: float = 35.0, key: str = "t1") -> TileLadder:
    return TileLadder(tile_key=key, base_threshold_c=base, hours=tuple(hours))


#: A realistic decaying curve: 12 h above 35 °C, falling to 0 by 45 °C.
DECAY = (12.0, 10.0, 8.5, 7.0, 5.5, 4.0, 3.0, 2.0, 1.0, 0.5, 0.0)


# ═════════════════════════════════════════════════════════════════════════════
# The ladder
# ═════════════════════════════════════════════════════════════════════════════


def test_hours_at_a_rung_is_the_measured_value() -> None:
    ladder = _ladder(*DECAY)
    assert ladder.hours_at(35.0) == 12.0
    assert ladder.hours_at(38.0) == 7.0
    assert ladder.hours_at(45.0) == 0.0


def test_hours_between_rungs_are_interpolated() -> None:
    """The ladder is sampled at whole degrees; a predicted ΔT rarely lands on one."""
    ladder = _ladder(*DECAY)
    assert ladder.hours_at(35.5) == pytest.approx(11.0)
    assert ladder.hours_at(37.5) == pytest.approx(7.75)


def test_hours_avoided_reads_the_curve_at_the_shifted_threshold() -> None:
    """The core conversion: 2 °C of cooling removes ladder(35) − ladder(37)."""
    ladder = _ladder(*DECAY)
    assert ladder.hours_avoided(-2.0) == pytest.approx(12.0 - 8.5)


def test_more_cooling_avoids_more_hours() -> None:
    ladder = _ladder(*DECAY)
    values = [ladder.hours_avoided(-d) for d in (0.5, 1.0, 2.0, 4.0, 8.0)]
    assert values == sorted(values)


def test_warming_avoids_nothing_rather_than_a_negative() -> None:
    """A negative "avoided" figure would let a bad intervention improve a total."""
    assert _ladder(*DECAY).hours_avoided(+1.5) == 0.0
    assert _ladder(*DECAY).hours_avoided(0.0) == 0.0


def test_cooling_beyond_the_ladder_is_refused() -> None:
    """Extrapolating past the top rung would invent hours the API never measured."""
    with pytest.raises(LadderError, match="exceeds the ladder"):
        _ladder(*DECAY).hours_avoided(-(MAX_EVALUABLE_DELTA_C + 0.1))


def test_threshold_above_the_top_rung_is_refused() -> None:
    with pytest.raises(LadderError, match="never measured"):
        _ladder(*DECAY).hours_at(46.0)


def test_threshold_below_the_base_is_refused() -> None:
    with pytest.raises(LadderError, match="below the ladder"):
        _ladder(*DECAY).hours_at(34.0)


def test_an_already_safe_tile_is_recognised() -> None:
    """A tile never above the threshold cannot benefit, however much it is cooled."""
    safe = _ladder(*([0.0] * 11))
    assert safe.is_already_safe
    assert safe.hours_avoided(-3.0) == 0.0


def test_flat_curve_never_yields_negative_zero() -> None:
    """Floating error on a flat curve would otherwise render "-0 hours avoided"."""
    flat = _ladder(*([6.0] * 11))
    assert flat.hours_avoided(-3.0) == 0.0


@pytest.mark.parametrize(
    "bad",
    [(-1.0, 0.0), (25.0, 1.0), (5.0,)],
)
def test_impossible_ladders_are_rejected(bad: tuple[float, ...]) -> None:
    with pytest.raises(LadderError):
        _ladder(*bad)


# ── Assembly ────────────────────────────────────────────────────────────────


def test_build_ladder_from_complete_rungs() -> None:
    ladder = build_ladder(
        tile_key="t1",
        base_threshold_c=35.0,
        hours_by_step=dict(enumerate(DECAY)),
    )
    assert ladder is not None
    assert ladder.hours == DECAY


def test_a_missing_rung_yields_no_ladder_rather_than_an_interpolated_one() -> None:
    """The most important rule here.

    Filling a gap would put a fabricated measurement where a real one is missing,
    and every downstream figure would inherit it with no way to tell.
    """
    steps: dict[int, float | None] = dict(enumerate(DECAY))
    steps[4] = None
    assert (
        build_ladder(tile_key="t1", base_threshold_c=35.0, hours_by_step=steps) is None
    )


def test_non_monotonic_rungs_are_clamped_not_propagated() -> None:
    """Hours cannot rise with threshold; propagating it yields negative avoidance."""
    broken = list(DECAY)
    broken[3] = 9.9  # higher than the rung below it
    ladder = build_ladder(
        tile_key="t1",
        base_threshold_c=35.0,
        hours_by_step=dict(enumerate(broken)),
    )
    assert ladder is not None
    assert ladder.hours[3] == ladder.hours[2]
    assert ladder.hours_avoided(-3.0) >= 0.0


# ── Derived quantities ──────────────────────────────────────────────────────


def test_person_heat_hours_is_none_when_population_is_unknown() -> None:
    """Zero would systematically deprioritise the worst-surveyed areas."""
    assert person_heat_hours(5.0, None) is None
    assert person_heat_hours(5.0, 100.0) == 500.0


def test_equity_weighting_needs_no_svi_to_produce_a_figure() -> None:
    assert equity_weighted(500.0, None, 1.0) == 500.0
    assert equity_weighted(500.0, 0.8, 1.0) == pytest.approx(900.0)


def test_lambda_zero_disables_the_equity_uplift() -> None:
    assert equity_weighted(500.0, 0.9, 0.0) == 500.0


# ═════════════════════════════════════════════════════════════════════════════
# Counterfactual
# ═════════════════════════════════════════════════════════════════════════════


def test_catalog_estimator_uses_the_cited_range_as_the_interval() -> None:
    estimate = CatalogDeltaEstimator().estimate(FakeEntry("tree"), TileContext("t1"))
    assert estimate.low == -2.5
    assert estimate.high == -0.4
    assert estimate.value == pytest.approx(-1.45)
    assert estimate.source == "catalog_effect_range"


def test_an_estimate_outside_its_own_interval_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="does not contain"):
        DeltaEstimate(value=-5.0, low=-2.0, high=-1.0, source="x")


def test_absurd_predictions_are_clamped_to_the_cited_range() -> None:
    """A model predicting 8 °C from one tree must not reach a display."""
    entry = FakeEntry("tree")
    wild = DeltaEstimate(value=-8.0, low=-9.0, high=-7.0, source="model")
    clamped = clamp_to_catalog(wild, entry)
    assert clamped.value == -2.5
    assert clamped.low >= -2.5
    assert clamped.high <= -0.4 or clamped.high == clamped.value


def test_clamping_also_bounds_the_interval() -> None:
    """A wide interval must not smuggle an absurd figure in through ci_low."""
    entry = FakeEntry("tree")
    wide = DeltaEstimate(value=-1.0, low=-20.0, high=5.0, source="model")
    clamped = clamp_to_catalog(wide, entry)
    assert clamped.low >= -2.5
    assert clamped.high <= -0.4


def test_an_in_range_estimate_is_untouched() -> None:
    entry = FakeEntry("tree")
    fine = DeltaEstimate(value=-1.2, low=-1.8, high=-0.6, source="model")
    assert clamp_to_catalog(fine, entry) == fine


# ── Feasibility ─────────────────────────────────────────────────────────────


def test_no_rule_means_always_feasible() -> None:
    assert check_feasibility(FakeEntry("tree"), TileContext("t1")) is None


def test_a_max_rule_excludes_a_tile_above_the_limit() -> None:
    entry = FakeEntry("tree", feasibility_rule={"max_canopy_pct": 40})
    reason = check_feasibility(entry, TileContext("t1", canopy_pct=62.0))
    assert reason is not None and "above the 40 limit" in reason


def test_a_min_rule_excludes_a_tile_below_the_limit() -> None:
    entry = FakeEntry("roof", feasibility_rule={"min_building_pct": 20})
    reason = check_feasibility(entry, TileContext("t1", building_pct=5.0))
    assert reason is not None and "below the 20 minimum" in reason


def test_an_unmeasured_feature_does_not_block_a_candidate() -> None:
    """Excluding every tile with a data gap would shrink the plan to the
    best-surveyed blocks, which are systematically not the ones that need it."""
    entry = FakeEntry("tree", feasibility_rule={"max_canopy_pct": 40})
    assert check_feasibility(entry, TileContext("t1", canopy_pct=None)) is None


def test_an_unknown_rule_key_is_ignored_not_treated_as_satisfied() -> None:
    entry = FakeEntry("tree", feasibility_rule={"max_unicorns": 3})
    assert check_feasibility(entry, TileContext("t1")) is None


# ═════════════════════════════════════════════════════════════════════════════
# Objectives
# ═════════════════════════════════════════════════════════════════════════════


def _delta(value: float = -1.5) -> DeltaEstimate:
    return DeltaEstimate(value=value, low=value - 0.5, high=value + 0.5, source="t")


def test_max_delta_ignores_exposure_entirely() -> None:
    """That is the point of offering it: "where can we cool most",
    not "who benefits".
    """
    args = {
        "objective": "max_delta_c",
        "delta": _delta(-2.0),
        "hours_avoided": 4.0,
        "svi_score": 0.9,
        "equity_lambda": 1.0,
    }
    crowded = objective_benefit(**args, person_hours_avoided=90_000.0)  # type: ignore[arg-type]
    empty = objective_benefit(**args, person_hours_avoided=1.0)  # type: ignore[arg-type]
    assert crowded == empty == 2.0


def test_person_heat_hours_objective_prefers_populated_tiles() -> None:
    base = {
        "objective": "max_person_heat_hours",
        "delta": _delta(),
        "hours_avoided": 4.0,
        "svi_score": None,
        "equity_lambda": 1.0,
    }
    crowded = objective_benefit(**base, person_hours_avoided=8_000.0)  # type: ignore[arg-type]
    sparse = objective_benefit(**base, person_hours_avoided=100.0)  # type: ignore[arg-type]
    assert crowded > sparse


def test_unknown_population_falls_back_to_raw_hours_not_zero() -> None:
    """Scoring zero would mean a census-gap tile could never be selected."""
    benefit = objective_benefit(
        objective="max_person_heat_hours",
        delta=_delta(),
        hours_avoided=4.0,
        person_hours_avoided=None,
        svi_score=None,
        equity_lambda=1.0,
    )
    assert benefit == 4.0


def test_equity_objective_uplifts_vulnerable_tiles() -> None:
    base = {
        "objective": "equity_weighted",
        "delta": _delta(),
        "hours_avoided": 4.0,
        "person_hours_avoided": 1_000.0,
        "equity_lambda": 2.0,
    }
    vulnerable = objective_benefit(**base, svi_score=0.9)  # type: ignore[arg-type]
    comfortable = objective_benefit(**base, svi_score=0.1)  # type: ignore[arg-type]
    assert vulnerable > comfortable


# ═════════════════════════════════════════════════════════════════════════════
# Selection
# ═════════════════════════════════════════════════════════════════════════════


def _candidate(
    tile: str,
    *,
    cost: float,
    benefit: float,
    hours: float = 3.0,
    code: str = "tree",
    people: float | None = 100.0,
) -> Candidate:
    return Candidate(
        tile_key=tile,
        intervention_code=code,
        quantity=12.0,
        cost_usd=cost,
        delta=_delta(),
        hours_avoided=hours,
        person_hours_avoided=None if people is None else hours * people,
        people_affected=people,
        benefit=benefit,
    )


def test_selection_never_exceeds_the_budget() -> None:
    candidates = [_candidate(f"t{i}", cost=3_000.0, benefit=100.0) for i in range(10)]
    result = select_plan(candidates=candidates, budget_usd=10_000.0)
    assert result.total_cost_usd <= 10_000.0
    assert len(result.selected) == 3


def test_the_most_cost_effective_candidate_is_chosen_first() -> None:
    cheap = _candidate("t1", cost=100.0, benefit=100.0)  # 1.0 per dollar
    dear = _candidate("t2", cost=1_000.0, benefit=200.0)  # 0.2 per dollar
    result = select_plan(candidates=[dear, cheap], budget_usd=100.0)
    assert [c.tile_key for c in result.selected] == ["t1"]


def test_a_cheaper_candidate_is_taken_after_an_unaffordable_one() -> None:
    """Stopping at the first miss would leave budget unspent for no reason."""
    big = _candidate("t1", cost=9_000.0, benefit=9_000.0)  # 1.0 per dollar
    small = _candidate("t2", cost=400.0, benefit=200.0)  # 0.5 per dollar
    result = select_plan(candidates=[big, small], budget_usd=1_000.0)
    assert [c.tile_key for c in result.selected] == ["t2"]


def test_one_intervention_per_tile() -> None:
    """Stacking would double count cooling the ladder converts only once."""
    a = _candidate("t1", cost=100.0, benefit=100.0, code="tree")
    b = _candidate("t1", cost=100.0, benefit=90.0, code="roof")
    result = select_plan(candidates=[a, b], budget_usd=10_000.0)
    assert len(result.selected) == 1
    assert result.selected[0].intervention_code == "tree"


def test_selection_is_deterministic_under_ties() -> None:
    """Two runs must not produce different plans with the same total."""
    tied = [_candidate(f"t{i}", cost=100.0, benefit=50.0) for i in range(6)]
    first = select_plan(candidates=list(reversed(tied)), budget_usd=300.0)
    second = select_plan(candidates=tied, budget_usd=300.0)
    assert [c.tile_key for c in first.selected] == [c.tile_key for c in second.selected]


def test_zero_cost_candidates_rank_first_without_breaking_the_sort() -> None:
    free = _candidate("t1", cost=0.0, benefit=10.0)
    paid = _candidate("t2", cost=100.0, benefit=1_000.0)
    result = select_plan(candidates=[paid, free], budget_usd=100.0)
    assert result.selected[0].tile_key == "t1"
    assert len(result.selected) == 2


def test_a_non_positive_budget_is_refused() -> None:
    for budget in (0.0, -1.0):
        with pytest.raises(ValueError, match="budget must be positive"):
            select_plan(candidates=[], budget_usd=budget)


def test_no_candidates_yields_an_empty_plan_not_an_error() -> None:
    result = select_plan(candidates=[], budget_usd=1_000.0)
    assert result.selected == []
    assert result.total_cost_usd == 0.0


def test_totals_sum_the_selected_items() -> None:
    result = select_plan(
        candidates=[
            _candidate("t1", cost=100.0, benefit=10.0, hours=3.0, people=200.0),
            _candidate("t2", cost=200.0, benefit=20.0, hours=5.0, people=300.0),
        ],
        budget_usd=1_000.0,
    )
    assert result.total_cost_usd == 300.0
    assert result.total_hours_avoided == 8.0
    assert result.total_person_hours_avoided == pytest.approx(3 * 200 + 5 * 300)
    assert result.people_reached == 500.0


# ── District mean ───────────────────────────────────────────────────────────


def test_district_mean_is_diluted_by_untreated_tiles() -> None:
    """Reporting the treated-tile mean would overstate a plan several times over."""
    result = select_plan(
        candidates=[_candidate(f"t{i}", cost=100.0, benefit=10.0) for i in range(10)],
        budget_usd=10_000.0,
    )
    value, low, high = mean_delta_over_aoi(result, total_tiles=1_000)
    assert value == pytest.approx(10 * -1.5 / 1_000)
    assert low <= value <= high


def test_district_mean_of_an_empty_aoi_is_zero_not_a_crash() -> None:
    assert mean_delta_over_aoi(select_plan(candidates=[], budget_usd=1.0), 0) == (
        0.0,
        0.0,
        0.0,
    )


# ═════════════════════════════════════════════════════════════════════════════
# End to end
# ═════════════════════════════════════════════════════════════════════════════


def test_candidates_are_built_scored_and_selected() -> None:
    catalog = [
        FakeEntry("tree", unit_cost_usd=Decimal("450.00")),
        FakeEntry(
            "roof",
            category="material",
            unit="m2",
            unit_cost_usd=Decimal("30.00"),
            delta_c_low=Decimal("-1.60"),
            delta_c_high=Decimal("-0.30"),
            feasibility_rule={"min_building_pct": 20},
        ),
    ]
    tiles = {
        "hot": TileContext("hot", building_pct=45.0, population=800.0, svi_score=0.9),
        "mild": TileContext("mild", building_pct=5.0, population=200.0, svi_score=0.2),
    }
    ladders = {
        "hot": _ladder(*DECAY, key="hot"),
        "mild": _ladder(*([2.0, 1.0] + [0.0] * 9), key="mild"),
    }

    candidates, infeasible, no_ladder = build_candidates(
        catalog=catalog,
        tiles=tiles,
        ladders=ladders,
        quantities={"tree": 12.0, "roof": 200.0},
        estimator=CatalogDeltaEstimator(),
        objective="equity_weighted",
        equity_lambda=1.0,
    )

    assert no_ladder == 0
    # The roof is infeasible on the low-building tile and recorded with a reason.
    assert any(
        i.tile_key == "mild" and i.intervention_code == "roof" for i in infeasible
    )
    assert candidates, "the hot tile must yield at least one candidate"

    result = select_plan(
        candidates=candidates, budget_usd=6_000.0, infeasible=infeasible
    )
    assert result.total_cost_usd <= 6_000.0
    assert len({c.tile_key for c in result.selected}) == len(result.selected)
    # The vulnerable, heavily-exposed tile is chosen over the mild one.
    assert result.selected[0].tile_key == "hot"


def test_tiles_without_a_ladder_are_counted_not_silently_dropped() -> None:
    candidates, _, no_ladder = build_candidates(
        catalog=[FakeEntry("tree")],
        tiles={"a": TileContext("a"), "b": TileContext("b")},
        ladders={"a": _ladder(*DECAY, key="a")},
        quantities={"tree": 1.0},
        estimator=CatalogDeltaEstimator(),
        objective="max_delta_c",
        equity_lambda=1.0,
    )
    assert no_ladder == 1
    assert {c.tile_key for c in candidates} == {"a"}


def test_an_already_safe_tile_is_excluded_with_a_reason() -> None:
    """The plan must not spend budget on blocks that were never at risk."""
    _, infeasible, _ = build_candidates(
        catalog=[FakeEntry("tree")],
        tiles={"safe": TileContext("safe", population=500.0)},
        ladders={"safe": _ladder(*([0.0] * 11), key="safe")},
        quantities={"tree": 1.0},
        estimator=CatalogDeltaEstimator(),
        objective="max_person_heat_hours",
        equity_lambda=1.0,
    )
    assert len(infeasible) == 1
    assert "no hours above the danger threshold" in infeasible[0].reason
