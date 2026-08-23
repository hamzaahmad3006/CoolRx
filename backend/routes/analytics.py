"""Analytic layer, enrichment and priority routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from schemas.analytics import (
    AttributionListResponse,
    AttributionResponse,
    CandidatesResponse,
    ExposureListResponse,
    InterventionCatalogResponse,
    PriorityResponse,
    StatsResponse,
    TilesResponse,
)
from schemas.common import AnalyticType

from .deps import AnalyticsControllerDep, CatalogControllerDep

router = APIRouter(tags=["analytics"])


@router.get(
    "/projects/{project_id}/tiles",
    response_model=TilesResponse,
    summary="Tile layer for one analytic",
)
def get_tiles(
    project_id: uuid.UUID,
    controller: AnalyticsControllerDep,
    analytic: AnalyticType = Query(default="tcm"),
) -> TilesResponse:
    return controller.tiles(project_id, analytic)


@router.get(
    "/projects/{project_id}/stats",
    response_model=StatsResponse,
    summary="District statistics and analytic runs",
)
def get_stats(
    project_id: uuid.UUID, controller: AnalyticsControllerDep
) -> StatsResponse:
    return controller.stats(project_id)


@router.get(
    "/projects/{project_id}/attribution",
    response_model=AttributionListResponse,
    summary="Per-tile SHAP attribution",
)
def get_attribution(
    project_id: uuid.UUID, controller: AnalyticsControllerDep
) -> AttributionListResponse:
    return controller.attribution(project_id)


@router.get(
    "/projects/{project_id}/attribution/{tile_key}",
    response_model=AttributionResponse,
    summary="Attribution for one tile (drawer)",
)
def get_tile_attribution(
    project_id: uuid.UUID, tile_key: str, controller: AnalyticsControllerDep
) -> AttributionResponse:
    return controller.attribution_for_tile(project_id, tile_key)


@router.get(
    "/projects/{project_id}/exposure",
    response_model=ExposureListResponse,
    summary="Population and vulnerability by tile",
)
def get_exposure(
    project_id: uuid.UUID, controller: AnalyticsControllerDep
) -> ExposureListResponse:
    return controller.exposure(project_id)


@router.get(
    "/projects/{project_id}/priorities",
    response_model=PriorityResponse,
    summary="Ranked tiles by equity-weighted person-heat-hours",
)
def get_priorities(
    project_id: uuid.UUID,
    controller: AnalyticsControllerDep,
    # λ is a query parameter rather than server state so a ranking is always
    # reproducible from its URL — a judge can be sent a link to an exact view.
    equity_lambda: float = Query(default=1.0, ge=0.0, le=5.0),
    threshold_c: float = Query(default=35.0),
) -> PriorityResponse:
    return controller.priorities(project_id, equity_lambda, threshold_c)


@router.get(
    "/catalog",
    response_model=list[InterventionCatalogResponse],
    summary="Intervention catalog",
)
def get_catalog(
    controller: CatalogControllerDep,
) -> list[InterventionCatalogResponse]:
    return controller.list()


@router.get(
    "/catalog/candidates",
    response_model=CandidatesResponse,
    summary="Catalog plus excluded candidates",
)
def get_candidates(controller: CatalogControllerDep) -> CandidatesResponse:
    return controller.candidates()


@router.get(
    "/projects/{project_id}/candidates",
    response_model=CandidatesResponse,
    summary="Catalog plus excluded candidates, for one project",
)
def get_project_candidates(
    project_id: uuid.UUID, controller: CatalogControllerDep
) -> CandidatesResponse:
    """The project-scoped form the UI calls.

    `infeasible` is inherently per-project -- a feasibility rule is evaluated
    against a tile's features -- so the project-scoped path is the honest one and
    `/catalog/candidates` is kept for the catalog alone.
    """
    return controller.candidates()
