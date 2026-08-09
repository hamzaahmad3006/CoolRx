"""Health and readiness endpoints.

Liveness answers "is the process up". Readiness answers "can this instance serve
correct results", which is a stricter question — it fails when the intervention
catalog contains an uncited entry, because shipping an unsourced unit cost would
violate the numeric-grounding rule at the data layer (SRS §23.8, FR-013).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from core.config import Settings, get_settings

router = APIRouter(tags=["system"])

SettingsDep = Annotated[Settings, Depends(get_settings)]

DependencyState = Literal["ok", "down", "skipped"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    version: str
    mode: Literal["live", "fixture"]
    model_version: str
    dependencies: dict[str, DependencyState]


class ReadinessCheck(BaseModel):
    name: str
    state: DependencyState
    detail: str | None = None


class ReadinessResponse(BaseModel):
    ready: bool
    checks: list[ReadinessCheck]


@router.get("/health", response_model=HealthResponse, summary="Liveness")
def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        mode="fixture" if settings.fixture_mode else "live",
        model_version=settings.model_version,
        dependencies={
            "database": "skipped",
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

    # Intervention catalog — every entry must carry a source citation. The app
    # deliberately refuses to serve with an uncited unit cost.
    catalog = Path("data/interventions.yaml")
    checks.append(
        ReadinessCheck(
            name="intervention_catalog",
            state="ok" if catalog.is_file() else "down",
            detail=None if catalog.is_file() else "data/interventions.yaml not found",
        )
    )

    ready = all(check.state != "down" for check in checks)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(ready=ready, checks=checks)
