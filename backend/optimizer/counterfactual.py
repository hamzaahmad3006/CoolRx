"""Per-tile cooling estimates for a candidate intervention.

Two estimators, one interface.

**Catalog estimator** (available now). ΔT comes from the intervention's published
effect range in `interventions_catalog`, which carries a required citation. The
midpoint is the point estimate and the published range *is* the interval. This is
not a fallback in any apologetic sense — a cited effect size from peer-reviewed
literature is a legitimate, traceable planning input, and it satisfies P1 and P2
exactly as a model prediction would.

**Model estimator** (Task 4). Re-runs p10/p50/p90 inference on a modified feature
vector and takes the difference from baseline. Strictly better because it varies
by tile, but it inherits the catalog's clamp either way.

Whichever produces the number, three rules hold:

  1. **ΔT is clamped to the cited range.** A model that predicts 8 °C from planting
     a tree is producing a physically absurd figure, and clamping makes it
     impossible to display one regardless of model behaviour.
  2. **Feasibility is checked first.** Planting trees on a tile that is 95% building
     footprint is not a cheap win, it is impossible, and the reason is recorded.
  3. **The interval is never dropped.** Every estimate carries low/high bounds, so a
     bare point estimate cannot reach the plan.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DeltaEstimate:
    """A cooling estimate with its interval, in °C. Cooling is negative."""

    value: float
    low: float
    high: float
    source: str

    def __post_init__(self) -> None:
        if not (self.low <= self.value <= self.high):
            raise ValueError(
                f"interval [{self.low}, {self.high}] does not contain {self.value}"
            )


class CatalogEntryLike(Protocol):
    """The catalog fields an estimator needs, so tests need no ORM rows."""

    code: str
    category: str
    unit: str
    unit_cost_usd: Decimal
    delta_c_low: Decimal
    delta_c_high: Decimal
    feasibility_rule: object


@dataclass(frozen=True, slots=True)
class TileContext:
    """Everything known about one tile when scoring a candidate."""

    tile_key: str
    canopy_pct: float | None = None
    impervious_pct: float | None = None
    building_pct: float | None = None
    water_pct: float | None = None
    grass_shrub_pct: float | None = None
    albedo_proxy: float | None = None
    population: float | None = None
    svi_score: float | None = None


@dataclass(frozen=True, slots=True)
class Infeasible:
    """Why a candidate was excluded. Returned, never silently dropped."""

    tile_key: str
    intervention_code: str
    reason: str


# ═════════════════════════════════════════════════════════════════════════════
# Feasibility
# ═════════════════════════════════════════════════════════════════════════════

#: Rule keys understood in `interventions_catalog.feasibility_rule`. An unknown key
#: is logged and ignored rather than silently treated as satisfied, because a
#: misspelled rule that quietly passes is worse than one that visibly does nothing.
_RULE_KEYS = frozenset(
    {
        "max_canopy_pct",
        "min_impervious_pct",
        "max_building_pct",
        "min_building_pct",
        "max_water_pct",
        "max_albedo_proxy",
    }
)


def check_feasibility(
    entry: CatalogEntryLike, tile: TileContext
) -> str | None:
    """Return the reason this intervention cannot go here, or None if it can.

    A rule whose tile feature is **unmeasured** does not block the candidate. The
    alternative — excluding every tile with a data gap — would quietly shrink the
    plan to only the best-surveyed blocks, which are systematically not the ones
    that need it most.
    """
    rule = entry.feasibility_rule
    if not isinstance(rule, dict) or not rule:
        return None

    for key, raw in rule.items():
        if key not in _RULE_KEYS:
            log.warning(
                "feasibility.unknown_rule",
                intervention=entry.code,
                rule_key=key,
                detail="ignored; not treated as satisfied",
            )
            continue

        try:
            limit = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            log.warning(
                "feasibility.unparsable_limit",
                intervention=entry.code,
                rule_key=key,
                value=repr(raw),
            )
            continue

        feature = key.split("_", 1)[1]
        value = getattr(tile, feature, None)
        if value is None:
            continue  # Unmeasured does not mean unsuitable.

        if key.startswith("max_") and value > limit:
            return f"{feature.replace('_', ' ')} is {value:g}, above the {limit:g} limit"
        if key.startswith("min_") and value < limit:
            return f"{feature.replace('_', ' ')} is {value:g}, below the {limit:g} minimum"

    return None


# ═════════════════════════════════════════════════════════════════════════════
# Estimators
# ═════════════════════════════════════════════════════════════════════════════


class DeltaEstimator(ABC):
    """Produces a cooling estimate for one intervention on one tile."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def estimate(
        self, entry: CatalogEntryLike, tile: TileContext
    ) -> DeltaEstimate: ...


class CatalogDeltaEstimator(DeltaEstimator):
    """ΔT from the intervention's cited effect range.

    Identical for every tile, which is the honest limitation: published effect
    sizes are population averages and do not know that one block is already shaded.
    The model estimator exists to fix that; until it does, this is a cited number
    rather than a guess, and it says so in `source`.
    """

    @property
    def name(self) -> str:
        return "catalog_effect_range"

    def estimate(self, entry: CatalogEntryLike, tile: TileContext) -> DeltaEstimate:
        low = float(entry.delta_c_low)
        high = float(entry.delta_c_high)
        return DeltaEstimate(
            value=(low + high) / 2.0,
            low=low,
            high=high,
            source=self.name,
        )


def clamp_to_catalog(
    estimate: DeltaEstimate, entry: CatalogEntryLike
) -> DeltaEstimate:
    """Force an estimate inside the intervention's cited range.

    The last line of defence on ΔT (SRS §9.3.2). Whatever a model predicts, a
    physically absurd cooling figure cannot be displayed — and the clamp is applied
    to the bounds too, so a wide model interval cannot smuggle one in through
    `ci_low`.
    """
    low = float(entry.delta_c_low)
    high = float(entry.delta_c_high)

    clamped_value = min(max(estimate.value, low), high)
    clamped_low = min(max(estimate.low, low), high)
    clamped_high = min(max(estimate.high, low), high)

    if (clamped_value, clamped_low, clamped_high) != (
        estimate.value,
        estimate.low,
        estimate.high,
    ):
        log.info(
            "counterfactual.clamped",
            intervention=entry.code,
            predicted=estimate.value,
            clamped_to=clamped_value,
            cited_range=[low, high],
        )

    return DeltaEstimate(
        value=clamped_value,
        low=min(clamped_low, clamped_value),
        high=max(clamped_high, clamped_value),
        source=estimate.source,
    )
