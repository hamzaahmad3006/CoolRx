"""Health and readiness endpoints.

Liveness answers "is the process up". Readiness answers "can this instance serve
correct results", which is a stricter question — it fails when the intervention
catalog contains an uncited entry, because shipping an unsourced unit cost would
violate the numeric-grounding rule at the data layer (SRS §23.8, FR-013).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from core.config import Settings, get_settings
from repositories.base import check_connectivity, postgis_available, session_scope
from repositories.catalog import CatalogError, assert_catalog_ready
from schemas.system import (
    DependencyState,
    HealthResponse,
    ReadinessCheck,
    ReadinessResponse,
)

router = APIRouter(tags=["system"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/health", response_model=HealthResponse, summary="Liveness")
def health(settings: SettingsDep) -> HealthResponse:
    database: DependencyState = "ok" if check_connectivity() else "down"
    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        version=settings.app_version,
        mode="fixture" if settings.fixture_mode else "live",
        model_version=settings.model_version,
        dependencies={
            "database": database,
            # Not probed here: liveness must stay cheap. Readiness probes them.
            "redis": "skipped",
            "fortyguard": "skipped" if settings.fixture_mode else "ok",
        },
    )


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness")
def readiness(settings: SettingsDep, response: Response) -> ReadinessResponse:
    checks: list[ReadinessCheck] = []

    # Model artifacts — inference cannot run without them.
    model_dir = Path(settings.model_dir)
    model_present = model_dir.is_dir() and any(model_dir.glob("*.txt"))
    checks.append(
        ReadinessCheck(
            name="model_artifacts",
            state="ok" if model_present else "down",
            detail=None if model_present else f"No model files in {model_dir}",
        )
    )

    # Fixture directory — required when fixture mode is on.
    if settings.fixture_mode:
        fixture_dir = Path(settings.fixture_dir)
        present = fixture_dir.is_dir()
        checks.append(
            ReadinessCheck(
                name="fixtures",
                state="ok" if present else "down",
                detail=None if present else f"Missing fixture dir {fixture_dir}",
            )
        )

    # Database and PostGIS — the catalog check below needs both, so they are
    # reported separately to make the cause of a failure unambiguous.
    database_up = check_connectivity()
    checks.append(
        ReadinessCheck(
            name="database",
            state="ok" if database_up else "down",
            detail=None if database_up else "Cannot connect to PostgreSQL",
        )
    )

    if database_up:
        postgis = postgis_available()
        checks.append(
            ReadinessCheck(
                name="postgis",
                state="ok" if postgis else "down",
                detail=None if postgis else "PostGIS extension not installed",
            )
        )

    # Redis — no jobs can run without it, so an analysis request would be accepted
    # and then immediately fail. Readiness reports it rather than letting that
    # happen per-request.
    from workers.queue import redis_available

    redis_up = redis_available()
    checks.append(
        ReadinessCheck(
            name="redis",
            state="ok" if redis_up else "down",
            detail=None if redis_up else "Cannot reach Redis; no jobs can be queued",
        )
    )

    # Intervention catalog — every entry must carry a source citation. The app
    # deliberately refuses to serve with an uncited unit cost (AC-23).
    #
    # Checked against the database, not the CSV: the database is what the
    # optimizer reads, so a valid CSV that was never loaded must still fail.
    if database_up:
        try:
            with session_scope() as session:
                rows = assert_catalog_ready(session)
            catalog_check = ReadinessCheck(
                name="intervention_catalog",
                state="ok",
                detail=f"{rows} cited entries",
            )
        except CatalogError as exc:
            catalog_check = ReadinessCheck(
                name="intervention_catalog", state="down", detail=str(exc)
            )
    else:
        catalog_check = ReadinessCheck(
            name="intervention_catalog",
            state="down",
            detail="Not verifiable — database unavailable",
        )
    checks.append(catalog_check)

    ready = all(check.state != "down" for check in checks)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(ready=ready, checks=checks)
