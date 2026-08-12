"""Conversions between the three representations of the same data.

CoolRx holds each domain object in three shapes: the public API schema, the
FortyGuard wire model, and the SQLAlchemy row. Every conversion lives here, for
one reason — a conversion scattered across controllers is a conversion that
eventually disagrees with itself, and for geometry that disagreement is silent
(wrong SRID, swapped lat/lon) rather than an exception.

The AOI deliberately has two separate types. `schemas.projects.AoiFeatureCollection`
is our public contract; `clients.fortyguard.models.AoiFeatureCollection` is their
request format. Collapsing them into one would couple our API to theirs, so a
change on their side would break our clients.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from clients.fortyguard import models as fg
from repositories.tables import (
    AgentRun,
    AnalyticRun,
    Attribution,
    Exposure,
    InterventionCatalogEntry,
    Job,
    Plan,
    PlanItem,
    Project,
    TileFeature as TileFeatureRow,
)
from schemas.agent import AgentNodeRecord, AgentRunResponse, GuardViolation
from schemas.analytics import (
    AnalyticRunResponse,
    AssetCounts,
    AttributionDriver,
    AttributionResponse,
    ExposureResponse,
    FgStats,
    InterventionCatalogResponse,
    TileFeaturesResponse,
)
from schemas.common import Estimate
from schemas.jobs import JobResponse
from schemas.plans import PlanItemResponse, PlanResponse, PlanTotals
from schemas.projects import AoiFeatureCollection, ProjectResponse

# ═════════════════════════════════════════════════════════════════════════════
# AOI: public schema ↔ FortyGuard wire model
# ═════════════════════════════════════════════════════════════════════════════


def aoi_to_fg(aoi: AoiFeatureCollection) -> fg.AoiFeatureCollection:
    """Convert our AOI to FortyGuard's request shape.

    Positions are `[lon, lat]` in both, so the coordinate order is preserved by
    doing nothing to it — stated explicitly because silently transposing here
    would produce a valid-looking request for a location on the other side of the
    world.
    """
    return fg.AoiFeatureCollection(
        type="FeatureCollection",
        features=[
            fg.AoiFeature(
                type="Feature",
                properties={},
                geometry=fg.PolygonGeometry(
                    type="Polygon",
                    coordinates=[
                        [[float(lon), float(lat)] for lon, lat in ring]
                        for ring in feature.geometry.coordinates
                    ],
                ),
            )
            for feature in aoi.features
        ],
    )


def aoi_to_geojson_dict(aoi: AoiFeatureCollection) -> dict[str, Any]:
    """The AOI's Polygon geometry as a plain dict, for `ST_GeomFromGeoJSON`.

    Returns the *geometry*, not the FeatureCollection: PostGIS expects a geometry
    object, and passing the collection produces a confusing parse error rather
    than a clear one.
    """
    geometry = aoi.features[0].geometry
    return {
        "type": "Polygon",
        "coordinates": [
            [[float(lon), float(lat)] for lon, lat in ring]
            for ring in geometry.coordinates
        ],
    }


def geojson_dict_to_aoi(geometry: dict[str, Any]) -> AoiFeatureCollection:
    """Rebuild the public AOI shape from a stored PostGIS geometry."""
    return AoiFeatureCollection.model_validate(
        {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": geometry, "properties": {}}
            ],
        }
    )


def exterior_ring(aoi: AoiFeatureCollection) -> list[list[float]]:
    """Exterior ring as nested lists, the form `geodesic_area_sqmi` expects."""
    return [
        [float(lon), float(lat)] for lon, lat in aoi.features[0].geometry.coordinates[0]
    ]


# ═════════════════════════════════════════════════════════════════════════════
# Rows → response schemas
# ═════════════════════════════════════════════════════════════════════════════


def _f(value: Decimal | float | None) -> float | None:
    """NUMERIC → float, preserving None.

    None must survive: it means the measurement is missing, and `float(None)`
    would raise while `float(value or 0)` would fabricate a zero reading.
    """
    return None if value is None else float(value)


def project_to_response(
    project: Project, aoi_geometry: dict[str, Any]
) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        city=project.city,
        state=project.state,
        aoi=geojson_dict_to_aoi(aoi_geometry),
        area_sq_mi=float(project.area_sqmi),
        is_preset=project.is_preset,
        created_at=project.created_at,
    )


def analytic_run_to_response(
    run: AnalyticRun, activity_id: str | None
) -> AnalyticRunResponse:
    return AnalyticRunResponse(
        id=run.id,
        project_id=run.project_id,
        analytic_type=run.analytic_type,  # type: ignore[arg-type]
        threshold_c=_f(run.threshold_c),
        direction=run.direction,  # type: ignore[arg-type]
        granularity=run.granularity_m,  # type: ignore[arg-type]
        start_date=run.start_date.isoformat(),
        start_time=run.start_time.strftime("%H:%M") if run.start_time else None,
        filter_type=run.filter_type,  # type: ignore[arg-type]
        units=run.units,
        stats=FgStats.model_validate(run.stats or {}),
        activity_id=activity_id,
        created_at=run.created_at,
    )


def tile_features_to_response(row: TileFeatureRow) -> TileFeaturesResponse:
    return TileFeaturesResponse(
        tile_key=row.tile_key,
        canopy_pct=_f(row.canopy_pct),
        impervious_pct=_f(row.impervious_pct),
        building_pct=_f(row.building_pct),
        water_pct=_f(row.water_pct),
        grass_shrub_pct=_f(row.grass_shrub_pct),
        albedo_proxy=_f(row.albedo_proxy),
        openness_proxy=_f(row.openness_proxy),
        elevation_m=_f(row.elevation_m),
        local_relief_m=_f(row.local_relief_m),
        dist_to_water_m=_f(row.dist_to_water_m),
        district_mean_c=_f(row.district_mean_c),
    )


def exposure_to_response(row: Exposure) -> ExposureResponse:
    assets = row.assets if isinstance(row.assets, dict) else {}
    return ExposureResponse(
        tile_key=row.tile_key,
        population=_f(row.population),
        pct_over65=_f(row.pct_over65),
        pct_poverty=_f(row.pct_poverty),
        svi_score=_f(row.svi_score),
        svi_source_geoid=row.svi_source_geoid,
        assets=AssetCounts.model_validate(assets),
    )


def attribution_to_response(row: Attribution) -> AttributionResponse:
    """Expand the stored SHAP blob into typed drivers.

    Shares are computed from absolute contributions so that opposing drivers do
    not cancel into a share above 1.0 — a tile can have canopy pushing it cooler
    and impervious surface pushing it hotter at once.
    """
    shap = row.shap if isinstance(row.shap, dict) else {}
    contributions: dict[str, float] = {
        str(key): float(value)
        for key, value in shap.items()
        if isinstance(value, (int, float))
    }
    total = sum(abs(v) for v in contributions.values())

    drivers = [
        AttributionDriver(
            feature=name,
            label=DRIVER_LABELS.get(name, name.replace("_", " ").capitalize()),
            contribution_c=value,
            share=(abs(value) / total) if total > 0 else 0.0,
        )
        for name, value in sorted(
            contributions.items(), key=lambda kv: abs(kv[1]), reverse=True
        )
    ]

    return AttributionResponse(
        tile_key=row.tile_key,
        model_version=row.model_version,
        anomaly=Estimate.from_decimals(
            value=row.predicted_anomaly_c,
            ci_low=row.ci_low_c,
            ci_high=row.ci_high_c,
            unit="celsius",
            model_version=row.model_version,
        ),
        drivers=drivers,
        top_driver=row.top_driver,
    )


#: Plain-language names for model features. A planner reading "impervious_pct"
#: learns nothing; "Paved and built surface" is the same fact in their language.
DRIVER_LABELS: dict[str, str] = {
    "canopy_pct": "Missing tree canopy",
    "impervious_pct": "Paved and built surface",
    "building_pct": "Building density",
    "water_pct": "Distance from water",
    "grass_shrub_pct": "Missing low vegetation",
    "albedo_proxy": "Dark surface materials",
    "openness_proxy": "Trapped heat between buildings",
    "elevation_m": "Elevation",
    "local_relief_m": "Local terrain",
    "dist_to_water_m": "Distance from water",
    "hour_utc": "Time of day",
    "doy": "Time of year",
    "latitude": "Latitude",
}


def catalog_to_response(row: InterventionCatalogEntry) -> InterventionCatalogResponse:
    return InterventionCatalogResponse(
        code=row.code,
        category=row.category,  # type: ignore[arg-type]
        name=row.name,
        unit=row.unit,
        unit_cost_usd=float(row.unit_cost_usd),
        delta_c_low=float(row.delta_c_low),
        delta_c_high=float(row.delta_c_high),
        lifespan_years=row.lifespan_years,
        maintenance_usd_yr=float(row.maintenance_usd_yr),
        source_citation=row.source_citation,
    )


def job_to_response(job: Job) -> JobResponse:
    """Row → response, computing elapsed time rather than storing it."""
    end = job.updated_at if job.status in {"completed", "failed", "degraded"} else None
    reference = end or datetime.now(UTC)
    created = job.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)

    return JobResponse(
        id=job.id,
        project_id=job.project_id,
        kind=job.kind,  # type: ignore[arg-type]
        status=job.status,  # type: ignore[arg-type]
        stage=job.stage,
        progress_pct=job.progress_pct,
        elapsed_s=max(0.0, (reference - created).total_seconds()),
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def plan_item_to_response(
    item: PlanItem, catalog: InterventionCatalogEntry | None
) -> PlanItemResponse:
    """Row → response, joining the catalog for display fields.

    A missing catalog entry is rendered as the raw code rather than dropping the
    item: the item is part of the plan and its cost is real, so hiding it would
    make the totals unexplainable.
    """
    return PlanItemResponse(
        id=item.id,
        rank=item.rank,
        tile_key=item.tile_key,
        intervention_code=item.intervention_code,
        intervention_name=catalog.name if catalog else item.intervention_code,
        category=(catalog.category if catalog else "green"),  # type: ignore[arg-type]
        quantity=float(item.quantity),
        unit=catalog.unit if catalog else "count",
        unit_cost_usd=float(catalog.unit_cost_usd) if catalog else 0.0,
        cost_usd=float(item.cost_usd),
        predicted_delta=Estimate.from_decimals(
            value=item.predicted_delta_c,
            ci_low=item.ci_low_c,
            ci_high=item.ci_high_c,
            unit="celsius",
            model_version="",
        ),
        heat_hours_avoided=float(item.heat_hours_avoided),
        person_heat_hours_avoided=float(item.person_heat_hours_avoided),
        people_affected=float(item.people_affected),
        marginal_benefit_per_usd=float(item.marginal_benefit_per_usd),
        rationale=item.rationale,
    )


def plan_to_response(
    plan: Plan,
    items: list[PlanItem],
    catalog_by_code: dict[str, InterventionCatalogEntry],
    pct_top_svi_quartile: float | None,
) -> PlanResponse:
    item_responses = [
        plan_item_to_response(item, catalog_by_code.get(item.intervention_code))
        for item in sorted(items, key=lambda i: i.rank)
    ]
    # The item estimates carry the plan's model version; setting it per item from
    # the plan keeps one source of truth for it.
    item_responses = [
        response.model_copy(
            update={
                "predicted_delta": response.predicted_delta.model_copy(
                    update={"model_version": plan.model_version}
                )
            }
        )
        for response in item_responses
    ]

    return PlanResponse(
        id=plan.id,
        project_id=plan.project_id,
        budget_usd=float(plan.budget_usd),
        objective=plan.objective,  # type: ignore[arg-type]
        equity_lambda=float(plan.equity_lambda),
        threshold_c=float(plan.threshold_c),
        model_version=plan.model_version,
        totals=PlanTotals(
            total_cost_usd=float(plan.total_cost_usd),
            budget_usd=float(plan.budget_usd),
            mean_delta=Estimate.from_decimals(
                value=plan.mean_delta_c,
                ci_low=plan.mean_delta_c_low,
                ci_high=plan.mean_delta_c_high,
                unit="celsius",
                model_version=plan.model_version,
            ),
            heat_hours_avoided=float(plan.heat_hours_avoided),
            person_heat_hours_avoided=float(plan.person_heat_hours_avoided),
            people_reached=float(plan.people_reached),
            pct_reached_top_svi_quartile=pct_top_svi_quartile,
        ),
        items=item_responses,
        created_at=plan.created_at,
    )


def agent_run_to_response(row: AgentRun) -> AgentRunResponse:
    nodes_raw = row.nodes if isinstance(row.nodes, list) else []
    violations_raw = (
        row.guard_violations if isinstance(row.guard_violations, list) else []
    )
    return AgentRunResponse(
        id=row.id,
        plan_id=row.plan_id,
        graph_version=row.graph_version,
        model=row.model,
        nodes=[AgentNodeRecord.model_validate(node) for node in nodes_raw],
        guard_verdict=row.guard_verdict,  # type: ignore[arg-type]
        guard_violations=[
            GuardViolation.model_validate(item) for item in violations_raw
        ],
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        duration_ms=row.duration_ms,
        created_at=row.created_at,
    )


def parse_geometry_json(raw: str | dict[str, Any] | None) -> dict[str, Any] | None:
    """`ST_AsGeoJSON` returns a string; accept either form."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    parsed: dict[str, Any] = json.loads(raw)
    return parsed
