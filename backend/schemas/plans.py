"""Plan schemas.

Every predicted value in a plan is an `Estimate`, so a response cannot carry a ΔT
without its interval. `estimate_disclaimer` is a required field rather than
something the client is trusted to add: a client that renders a plan has, by
construction, received the statement that these are planning-grade estimates and
not measurements (SRS principle P4).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from .analytics import TileFeature
from .common import (
    ESTIMATE_DISCLAIMER,
    LADDER_ASSUMPTION,
    ApiModel,
    Estimate,
    InterventionCategory,
    PlanObjective,
    RequestModel,
)


class CreatePlanRequest(RequestModel):
    budget_usd: float = Field(gt=0, le=1_000_000_000, description="Hard ceiling.")
    objective: PlanObjective
    #: Equity weight in PHH × (1 + λ·SVI). Exposed as a parameter because it is a
    #: policy choice, not a physical constant — λ=0 optimises pure heat-hours,
    #: higher values prioritise vulnerable populations. The chosen value is echoed
    #: on every response so a plan is never shown without the weighting that
    #: produced it.
    equity_lambda: float = Field(default=1.0, ge=0.0, le=5.0)
    threshold_c: float | None = Field(
        default=None,
        description="Defaults to the project's diagnosis threshold when omitted.",
    )


class PlanItemResponse(ApiModel):
    id: uuid.UUID
    rank: int
    tile_key: str
    intervention_code: str
    #: Joined from the catalog so the client renders a name and category without a
    #: second request.
    intervention_name: str
    category: InterventionCategory
    quantity: float
    unit: str
    unit_cost_usd: float
    cost_usd: float
    #: Always an interval. The database CHECK guarantees it is well-ordered.
    predicted_delta: Estimate
    heat_hours_avoided: float
    person_heat_hours_avoided: float
    people_affected: float
    #: The selection criterion, recorded at selection time so the ranking can be
    #: audited rather than taken on trust.
    marginal_benefit_per_usd: float
    #: LLM-authored prose. Null by design — the plan is valid without it, which is
    #: the structural expression of "the language model is not load-bearing".
    rationale: str | None


class PlanTotals(ApiModel):
    total_cost_usd: float
    budget_usd: float
    #: Area-weighted across the whole AOI including untreated tiles, so this is
    #: not the mean of the item deltas and will normally be smaller.
    mean_delta: Estimate
    heat_hours_avoided: float
    person_heat_hours_avoided: float
    people_reached: float
    #: Share of people reached who live in the most vulnerable SVI quartile.
    #: Computed on read from `exposure`, not stored: it depends on the quartile
    #: cut, which is a property of the AOI rather than of the plan. Null when
    #: exposure data is too sparse to compute it honestly.
    pct_reached_top_svi_quartile: float | None = None


class PlanResponse(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    budget_usd: float
    objective: PlanObjective
    equity_lambda: float
    threshold_c: float
    model_version: str
    totals: PlanTotals
    items: list[PlanItemResponse]
    #: Required, with a default so it cannot be forgotten at a construction site.
    estimate_disclaimer: str = ESTIMATE_DISCLAIMER
    #: Present when heat-hours figures came from the exceedance ladder, naming the
    #: uniform-diurnal-shift assumption they rest on.
    ladder_assumption: str = LADDER_ASSUMPTION
    created_at: datetime


class ListPlansResponse(ApiModel):
    plans: list[PlanResponse]


class CounterfactualResponse(ApiModel):
    """The predicted post-intervention field, for the swipe map.

    `scale_domain` is singular and required. Both sides of a before/after
    comparison must be drawn on one colour scale; two independently-scaled halves
    would make a modest cooling look dramatic, so the API returns the shared
    domain rather than letting each side compute its own.
    """

    features: list[TileFeature]
    scale_domain: tuple[float, float]
    units: str | None
    #: Tiles the model refused to predict because the modified feature vector fell
    #: outside its training support. Returned explicitly rather than silently
    #: omitted — a gap in the after-map needs a reason.
    out_of_support_tile_keys: list[str] = Field(default_factory=list)
    estimate_disclaimer: str = ESTIMATE_DISCLAIMER


class DeltaHistogramBin(ApiModel):
    lower_c: float
    upper_c: float
    tile_count: int


class ImpactSummaryResponse(ApiModel):
    """Headline tiles for the Before/After page."""

    mean_delta: Estimate
    max_delta: Estimate
    tiles_treated: int
    tiles_total: int
    heat_hours_avoided: float
    person_heat_hours_avoided: float
    people_reached: float
    histogram: list[DeltaHistogramBin]
    estimate_disclaimer: str = ESTIMATE_DISCLAIMER


# ═════════════════════════════════════════════════════════════════════════════
# Equity
# ═════════════════════════════════════════════════════════════════════════════


class EquityDecile(ApiModel):
    """One SVI decile.

    `decile` is 1-based with 10 the most vulnerable, stated here because an
    off-by-one in either direction would invert the entire equity narrative.
    """

    decile: int = Field(ge=1, le=10)
    population: float
    person_heat_hours: float
    person_heat_hours_avoided: float
    share_of_benefit: float = Field(ge=0.0, le=1.0)


class VulnerableGroupBreakdown(ApiModel):
    group: str
    population_reached: float
    share_of_group_reached: float = Field(ge=0.0, le=1.0)
    person_heat_hours_avoided: float


class EquityResponse(ApiModel):
    plan_id: uuid.UUID
    equity_lambda: float
    deciles: list[EquityDecile]
    groups: list[VulnerableGroupBreakdown]
    #: SVI is tract-resolution while tiles are 60-100 m, so a tile inherits its
    #: tract's score. Carried in the payload so the caveat travels with the data
    #: rather than living only in the page that happens to render it.
    resolution_caveat: str = (
        "Social Vulnerability Index is published at census-tract resolution, "
        "coarser than the analysis tiles. Each tile inherits its tract's score, "
        "so within-tract variation is not represented."
    )
    estimate_disclaimer: str = ESTIMATE_DISCLAIMER
