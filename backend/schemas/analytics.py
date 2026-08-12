"""Analytic run, tile and enrichment schemas.

Two things are load-bearing in this module.

**`units` is echoed, never assumed.** Every response that carries measured values
includes the unit string read from the FortyGuard response's own `stats_data`. SRS
C-4 records that the documented unit and the returned unit have disagreed, so the
client is told what came back rather than what should have.

**`value` is `float | None`.** A null tile means the API returned no measurement
there. It is never coerced to 0, which would put a fabricated reading of zero
degrees on a map, and the map renders nulls with an explicit no-data pattern.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import (
    AnalyticType,
    ApiModel,
    Direction,
    Estimate,
    FilterType,
    Granularity,
    InterventionCategory,
    RiskLevel,
)

# ═════════════════════════════════════════════════════════════════════════════
# Analytic runs
# ═════════════════════════════════════════════════════════════════════════════


class FgStats(ApiModel):
    """Statistics block from a FortyGuard response.

    All fields optional: the API's `stats_data` contents vary by analytic type,
    and requiring a field that a given type omits would reject a valid response.
    """

    min: float | None = None
    max: float | None = None
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    count: int | None = None
    units: str | None = None


class AnalyticRunResponse(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    analytic_type: AnalyticType
    threshold_c: float | None
    direction: Direction | None
    granularity: Granularity
    start_date: str
    start_time: str | None
    filter_type: FilterType
    #: From the response's stats_data, not from the docs (SRS C-4).
    units: str | None
    stats: FgStats
    #: The provenance anchor. Joined from fg_requests — every displayed figure
    #: traces back to this handle (principle P2).
    activity_id: str | None
    created_at: datetime


# ═════════════════════════════════════════════════════════════════════════════
# Tiles
# ═════════════════════════════════════════════════════════════════════════════


class TileProperties(ApiModel):
    tile_key: str
    #: None means the API returned no measurement for this tile.
    value: float | None
    #: Centroid, carried in properties so the swipe-compare map can filter by
    #: longitude without a second geometry lookup.
    cx: float
    cy: float


class TileFeature(ApiModel):
    type: Literal["Feature"] = "Feature"
    id: str
    #: GeoJSON geometry as produced by ST_AsGeoJSON. Typed loosely on purpose:
    #: this is passed through to MapLibre untouched and never inspected here.
    geometry: dict[str, str | list[list[list[float]]]]
    properties: TileProperties


class TilesResponse(ApiModel):
    analytic: AnalyticType
    #: Echoed from the API's own stats_data.
    units: str | None
    threshold_c: float | None
    granularity: Granularity
    tile_count: int
    #: Tiles that returned no value. Surfaced so the UI can state coverage rather
    #: than let a sparse layer look like a complete one.
    null_count: int
    activity_id: str | None
    features: list[TileFeature]


class StatsResponse(ApiModel):
    analytic_runs: list[AnalyticRunResponse]
    stats: FgStats
    #: Value above which a tile is treated as a hotspot, in the analytic's units.
    hotspot_cutoff: float | None
    district_mean_c: float | None


# ═════════════════════════════════════════════════════════════════════════════
# Enrichment — features, exposure, attribution
# ═════════════════════════════════════════════════════════════════════════════


class TileFeaturesResponse(ApiModel):
    """Land-cover and terrain features for one tile.

    Every field is nullable. The upstream datasets have genuine gaps — NLCD does
    not cover every cell, elevation tiles have voids — and a schema that required
    these would force the enrichment step to invent values to satisfy it.
    """

    tile_key: str
    canopy_pct: float | None = None
    impervious_pct: float | None = None
    building_pct: float | None = None
    water_pct: float | None = None
    grass_shrub_pct: float | None = None
    albedo_proxy: float | None = None
    #: OSM building-footprint density. NOT a sky-view factor — no reliable free
    #: national building-height dataset exists (SRS NG-12).
    openness_proxy: float | None = None
    elevation_m: float | None = None
    local_relief_m: float | None = None
    dist_to_water_m: float | None = None
    district_mean_c: float | None = None


class AssetCounts(ApiModel):
    bus_stop: int = 0
    school: int = 0
    park: int = 0
    playground: int = 0
    hospital: int = 0


class ExposureResponse(ApiModel):
    tile_key: str
    #: Dasymetric estimate distributed from census block groups — non-integer by
    #: construction. It is not a headcount and is not presented as one.
    population: float | None = None
    pct_over65: float | None = None
    pct_poverty: float | None = None
    #: Census-TRACT resolution, coarser than a tile. The UI labels it as such
    #: rather than implying tile-level precision.
    svi_score: float | None = None
    svi_source_geoid: str | None = None
    assets: AssetCounts = Field(default_factory=AssetCounts)


class AttributionDriver(ApiModel):
    """One SHAP contribution, in degrees.

    `contribution_c` is signed and in °C rather than a normalised importance,
    because a planner needs to know how much of the anomaly a driver accounts
    for, not merely its rank.
    """

    feature: str
    label: str = Field(description="Plain-language label, e.g. 'Missing tree canopy'.")
    contribution_c: float
    share: float = Field(ge=0.0, le=1.0, description="Share of explained anomaly.")


class AttributionResponse(ApiModel):
    tile_key: str
    model_version: str
    #: Anomaly against the district mean, always with its interval.
    anomaly: Estimate
    drivers: list[AttributionDriver]
    top_driver: str


class AttributionListResponse(ApiModel):
    items: list[AttributionResponse]


class ExposureListResponse(ApiModel):
    items: list[ExposureResponse]


# ═════════════════════════════════════════════════════════════════════════════
# Prioritisation
# ═════════════════════════════════════════════════════════════════════════════


class TilePriorityResponse(ApiModel):
    tile_key: str
    rank: int
    risk_level: RiskLevel
    exceedance_hours: float | None
    persistence_hours: float | None
    #: Peak hour converted to LOCAL time. The API returns UTC; showing a planner
    #: a UTC peak hour would put the hottest moment of a Phoenix afternoon in the
    #: middle of the night.
    peak_hour_local: int | None = Field(default=None, ge=0, le=23)
    population: float | None
    #: population × exceedance_hours. A derived quantity with units, not an index.
    person_heat_hours: float | None
    #: person_heat_hours × (1 + λ·SVI). λ is a policy choice, echoed below so the
    #: client never has to assume which value produced this ranking.
    equity_weighted_phh: float | None


class PriorityResponse(ApiModel):
    items: list[TilePriorityResponse]
    equity_lambda: float
    threshold_c: float


# ═════════════════════════════════════════════════════════════════════════════
# Candidates
# ═════════════════════════════════════════════════════════════════════════════


class InterventionCatalogResponse(ApiModel):
    code: str
    category: InterventionCategory
    name: str
    unit: str
    unit_cost_usd: float
    delta_c_low: float
    delta_c_high: float
    lifespan_years: int
    maintenance_usd_yr: float
    #: Required. The app refuses to start with an uncited entry (AC-23).
    source_citation: str


class InfeasibleCandidate(ApiModel):
    """A candidate the optimizer excluded, with the reason.

    Returned rather than dropped: showing why an obvious intervention was not
    selected is what makes the plan auditable instead of oracular.
    """

    tile_key: str
    intervention_code: str
    reason: str


class CandidatesResponse(ApiModel):
    catalog: list[InterventionCatalogResponse]
    infeasible: list[InfeasibleCandidate]
