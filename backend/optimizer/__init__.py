"""Prioritisation and plan optimisation.

Pure computation over already-persisted data. Nothing here opens an HTTP
connection or writes to the database — the controller supplies inputs and stores
outputs, which is what makes the whole selection reproducible in a test.
"""

from __future__ import annotations

from .counterfactual import (
    CatalogDeltaEstimator,
    CatalogEntryLike,
    DeltaEstimate,
    DeltaEstimator,
    Infeasible,
    TileContext,
    check_feasibility,
    clamp_to_catalog,
)
from .ladder import (
    LADDER_STEPS,
    MAX_EVALUABLE_DELTA_C,
    LadderError,
    TileLadder,
    build_ladder,
    equity_weighted,
    person_heat_hours,
)
from .priorities import assign_risk_level, rank_tiles, utc_hour_to_local
from .select import (
    MAX_PLAN_ITEMS,
    Candidate,
    Objective,
    PlanResult,
    build_candidates,
    mean_delta_over_aoi,
    objective_benefit,
    select_plan,
    to_decimal,
)

__all__ = [
    "LADDER_STEPS",
    "MAX_EVALUABLE_DELTA_C",
    "MAX_PLAN_ITEMS",
    "Candidate",
    "CatalogDeltaEstimator",
    "CatalogEntryLike",
    "DeltaEstimate",
    "DeltaEstimator",
    "Infeasible",
    "LadderError",
    "Objective",
    "PlanResult",
    "TileContext",
    "TileLadder",
    "assign_risk_level",
    "build_candidates",
    "build_ladder",
    "check_feasibility",
    "clamp_to_catalog",
    "equity_weighted",
    "mean_delta_over_aoi",
    "objective_benefit",
    "person_heat_hours",
    "rank_tiles",
    "select_plan",
    "to_decimal",
    "utc_hour_to_local",
]
