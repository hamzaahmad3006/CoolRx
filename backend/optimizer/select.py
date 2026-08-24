"""Budget-constrained plan selection.

A greedy marginal-benefit-per-dollar knapsack. Greedy rather than exact, and the
reason is worth stating because "we used a heuristic" is usually a smell:

  * The value here is **explainability**, not the last 2% of optimality. Every
    selection can be justified to a city council in one sentence — "it delivered
    the most person-heat-hours per dollar of anything left that fit" — and the
    selection criterion is stored per item so the ranking can be audited later.
  * The inputs carry far more uncertainty than the algorithm does. ΔT comes from a
    published range spanning a factor of several; optimising exactly against numbers
    that soft is false precision.
  * A 0/1 knapsack over ~7,000 tiles × N interventions is solvable, but the result
    would differ from greedy by less than the width of a single prediction interval.

Two properties are guaranteed rather than hoped for:

  1. **The budget is never exceeded.** Checked before each selection, asserted after,
     and enforced again by a database CHECK constraint.
  2. **One intervention per tile.** Stacking two treatments on one block would double
     count their cooling — the ladder converts a single ΔT, not a sum of overlapping
     physical effects whose interaction nobody measured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, Literal

import structlog

from .counterfactual import (
    CatalogEntryLike,
    DeltaEstimate,
    DeltaEstimator,
    Infeasible,
    TileContext,
    check_feasibility,
    clamp_to_catalog,
)
from .ladder import LadderError, TileLadder, equity_weighted, person_heat_hours

log = structlog.get_logger(__name__)

Objective = Literal["max_delta_c", "max_person_heat_hours", "equity_weighted"]

#: Guard against a pathological run. A plan with more items than this is not a plan
#: a city can execute, and it usually means the budget or unit costs are wrong.
MAX_PLAN_ITEMS: Final[int] = 2_000


@dataclass(frozen=True, slots=True)
class Candidate:
    """One (tile, intervention) pair, scored and ready to rank."""

    tile_key: str
    intervention_code: str
    quantity: float
    cost_usd: float
    delta: DeltaEstimate
    hours_avoided: float
    person_hours_avoided: float | None
    people_affected: float | None
    #: The objective's benefit for this candidate, already weighted.
    benefit: float

    @property
    def benefit_per_usd(self) -> float:
        # A zero-cost candidate (a policy change) is infinitely cost-effective in
        # the literal sense; it is given the highest finite priority instead so the
        # ranking stays sortable and reproducible.
        if self.cost_usd <= 0:
            return float("inf") if self.benefit > 0 else 0.0
        return self.benefit / self.cost_usd


@dataclass(slots=True)
class PlanResult:
    selected: list[Candidate] = field(default_factory=list)
    infeasible: list[Infeasible] = field(default_factory=list)
    #: Candidates that were feasible and affordable but lost on cost-effectiveness.
    considered: int = 0
    #: Tiles skipped because their ladder was incomplete, so hours avoided could
    #: not be computed without inventing a measurement.
    tiles_without_ladder: int = 0

    @property
    def total_cost_usd(self) -> float:
        return sum(item.cost_usd for item in self.selected)

    @property
    def total_hours_avoided(self) -> float:
        return sum(item.hours_avoided for item in self.selected)

    @property
    def total_person_hours_avoided(self) -> float:
        return sum(item.person_hours_avoided or 0.0 for item in self.selected)

    @property
    def people_reached(self) -> float:
        return sum(item.people_affected or 0.0 for item in self.selected)


def objective_benefit(
    *,
    objective: Objective,
    delta: DeltaEstimate,
    hours_avoided: float,
    person_hours_avoided: float | None,
    svi_score: float | None,
    equity_lambda: float,
) -> float:
    """Benefit under the chosen objective.

    `max_delta_c` uses the magnitude of cooling and ignores exposure entirely —
    which is the point of offering it. It answers "where can we cool the most?"
    rather than "where does cooling help the most people?", and a planner comparing
    the two plans learns something real about their district.
    """
    if objective == "max_delta_c":
        return max(0.0, -delta.value)

    if objective == "max_person_heat_hours":
        # Falls back to raw hours where population is unknown, so a tile with a
        # census gap still competes rather than scoring zero and never being chosen.
        return (
            person_hours_avoided if person_hours_avoided is not None else hours_avoided
        )

    weighted = equity_weighted(person_hours_avoided, svi_score, equity_lambda)
    if weighted is not None:
        return weighted
    return hours_avoided


def build_candidates(
    *,
    catalog: list[CatalogEntryLike],
    tiles: dict[str, TileContext],
    ladders: dict[str, TileLadder],
    quantities: dict[str, float],
    estimator: DeltaEstimator,
    objective: Objective,
    equity_lambda: float,
) -> tuple[list[Candidate], list[Infeasible], int]:
    """Score every (tile, intervention) pair.

    `quantities` maps an intervention code to how many units are applied per tile —
    a planning convention (for example, twelve trees per block) rather than
    something derived, so it is supplied by the caller and recorded on the item.

    Returns `(candidates, infeasible, tiles_without_ladder)`.
    """
    candidates: list[Candidate] = []
    infeasible: list[Infeasible] = []
    no_ladder: set[str] = set()

    for tile_key, tile in tiles.items():
        ladder = ladders.get(tile_key)
        if ladder is None:
            no_ladder.add(tile_key)
            continue

        for entry in catalog:
            reason = check_feasibility(entry, tile)
            if reason is not None:
                infeasible.append(
                    Infeasible(
                        tile_key=tile_key,
                        intervention_code=entry.code,
                        reason=reason,
                    )
                )
                continue

            delta = clamp_to_catalog(estimator.estimate(entry, tile), entry)

            try:
                hours = ladder.hours_avoided(delta.value)
            except LadderError as exc:
                infeasible.append(
                    Infeasible(
                        tile_key=tile_key,
                        intervention_code=entry.code,
                        reason=str(exc),
                    )
                )
                continue

            # A tile already below the danger threshold gains no hours. It is
            # excluded with a reason rather than ranked at zero, so the plan does
            # not spend a budget on blocks that were never at risk.
            if hours <= 0:
                infeasible.append(
                    Infeasible(
                        tile_key=tile_key,
                        intervention_code=entry.code,
                        reason=(
                            "no hours above the danger threshold to avoid here"
                            if ladder.is_already_safe
                            else "predicted cooling removes no threshold hours"
                        ),
                    )
                )
                continue

            quantity = quantities.get(entry.code, 1.0)
            cost = quantity * float(entry.unit_cost_usd)
            phh = person_heat_hours(hours, tile.population)

            candidates.append(
                Candidate(
                    tile_key=tile_key,
                    intervention_code=entry.code,
                    quantity=quantity,
                    cost_usd=cost,
                    delta=delta,
                    hours_avoided=hours,
                    person_hours_avoided=phh,
                    people_affected=tile.population,
                    benefit=objective_benefit(
                        objective=objective,
                        delta=delta,
                        hours_avoided=hours,
                        person_hours_avoided=phh,
                        svi_score=tile.svi_score,
                        equity_lambda=equity_lambda,
                    ),
                )
            )

    return candidates, infeasible, len(no_ladder)


def select_plan(
    *,
    candidates: list[Candidate],
    budget_usd: float,
    infeasible: list[Infeasible] | None = None,
    tiles_without_ladder: int = 0,
) -> PlanResult:
    """Greedy selection under the budget, at most one intervention per tile.

    Ties are broken by tile key so a rerun on identical inputs produces an identical
    plan. Without that, two runs could return different plans with the same total,
    and a city comparing yesterday's PDF with today's would see unexplained churn.
    """
    if budget_usd <= 0:
        raise ValueError(f"budget must be positive, got {budget_usd}")

    result = PlanResult(
        infeasible=list(infeasible or []),
        considered=len(candidates),
        tiles_without_ladder=tiles_without_ladder,
    )

    ranked = sorted(
        candidates,
        key=lambda c: (-c.benefit_per_usd, c.tile_key, c.intervention_code),
    )

    remaining = budget_usd
    treated: set[str] = set()

    for candidate in ranked:
        if len(result.selected) >= MAX_PLAN_ITEMS:
            log.warning(
                "plan.item_cap_reached",
                cap=MAX_PLAN_ITEMS,
                detail="unit costs or budget are probably wrong",
            )
            break

        if candidate.tile_key in treated:
            # Stacking would double count: the ladder converts one ΔT, not a sum of
            # overlapping physical effects whose interaction nobody measured.
            continue

        if candidate.cost_usd > remaining:
            # Continue rather than break. A cheaper, slightly less efficient
            # candidate further down the list may still fit, and stopping at the
            # first miss would leave budget unspent for no reason.
            continue

        result.selected.append(candidate)
        treated.add(candidate.tile_key)
        remaining -= candidate.cost_usd

    total = result.total_cost_usd
    # The guarantee, asserted rather than assumed. The database CHECK enforces it
    # again, but failing here names the optimizer instead of a constraint.
    if total > budget_usd + 1e-6:
        raise AssertionError(
            f"selection totalled {total} against a budget of {budget_usd}"
        )

    log.info(
        "plan.selected",
        items=len(result.selected),
        considered=result.considered,
        infeasible=len(result.infeasible),
        tiles_without_ladder=tiles_without_ladder,
        total_cost_usd=round(total, 2),
        budget_usd=budget_usd,
        utilisation=round(total / budget_usd, 4) if budget_usd else 0.0,
    )
    return result


def mean_delta_over_aoi(
    result: PlanResult, total_tiles: int
) -> tuple[float, float, float]:
    """Area-weighted mean ΔT across the whole AOI, with its interval.

    Untreated tiles contribute zero, which is why this is normally much smaller than
    the mean of the selected items' deltas. Reporting the item mean as the district
    effect would overstate a plan by the ratio of treated to total tiles — often ten
    times or more.
    """
    if total_tiles <= 0:
        return 0.0, 0.0, 0.0

    value = sum(item.delta.value for item in result.selected) / total_tiles
    low = sum(item.delta.low for item in result.selected) / total_tiles
    high = sum(item.delta.high for item in result.selected) / total_tiles
    # Ordering is asserted because the caller writes these into interval-CHECKed
    # columns; a float sum can invert a degenerate interval.
    return value, min(low, value), max(high, value)


def to_decimal(value: float, places: str = "0.01") -> Decimal:
    """Round for persistence into a NUMERIC column."""
    return Decimal(str(value)).quantize(Decimal(places))
