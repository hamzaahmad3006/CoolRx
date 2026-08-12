"""Project and AOI controller.

The validation ordering here is deliberate: an AOI is checked *before* anything
is persisted and long before a credit is spent, because the whole point of the
pre-flight validator is that a rejected request costs nothing. SRS §11 records
that FortyGuard deducts credits only on success, but a failed request still
consumes a submission slot and wall-clock time in a demo.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.orm import Session

from clients.fortyguard.validation import (
    ValidationLimits,
    geodesic_area_sqmi,
    validate_aoi,
)
from core.config import Settings
from repositories.projects import ProjectRepository
from schemas.projects import (
    AoiFeatureCollection,
    AoiViolation,
    CreateProjectRequest,
    ListProjectsResponse,
    ProjectResponse,
    ValidateAoiResponse,
)

from .adapters import (
    aoi_to_fg,
    aoi_to_geojson_dict,
    exterior_ring,
    project_to_response,
)
from .errors import AoiRejectedError, NotFoundError

log = structlog.get_logger(__name__)

#: Credits a full diagnosis costs: one `tcm`, one `time_of_measure`, one
#: `persistence`, plus 11 `exceedance` steps for the ladder. Stated as a
#: breakdown rather than a magic number so the estimate can be checked.
DIAGNOSE_BASE_CREDITS = 3
LADDER_CREDITS = 11


def limits_from_settings(settings: Settings) -> ValidationLimits:
    """Build validator limits from configuration.

    The AOI cap is plan-dependent (10 mi² Basic, 50 Premium) and the plan granted
    to hackathon participants is undocumented (SRS C-8), so it comes from config
    rather than being hardcoded.
    """
    return ValidationLimits(
        max_aoi_sqmi=settings.fg_max_aoi_sqmi,
        date_floor=settings.fg_date_floor,
        granularity_options=tuple(settings.fg_granularity_options),
    )


def _to_api_violations(raw: list[Any]) -> list[AoiViolation]:
    """Map validator violations onto the public codes.

    The validator's `ViolationCode` is a `StrEnum` whose members match the public
    codes by name, so the mapping is by value — but it is done explicitly rather
    than by cast, because a code added on one side and not the other should fail
    loudly here instead of serialising an unknown string to the client.
    """
    violations: list[AoiViolation] = []
    for item in raw:
        violations.append(
            AoiViolation.model_validate(
                {
                    "code": str(item.code),
                    "message": item.message,
                    "field": item.field,
                }
            )
        )
    return violations


class ProjectController:
    def __init__(self, session: Session, settings: Settings) -> None:
        self._repo = ProjectRepository(session)
        self._settings = settings
        self._limits = limits_from_settings(settings)

    # ── Validation ───────────────────────────────────────────────────────────

    def validate_aoi(self, aoi: AoiFeatureCollection) -> ValidateAoiResponse:
        """Pre-flight an AOI without persisting or spending anything."""
        area = geodesic_area_sqmi(exterior_ring(aoi))
        raw_violations = validate_aoi(aoi_to_fg(aoi), self._limits)
        violations = _to_api_violations(raw_violations)

        return ValidateAoiResponse(
            is_valid=not violations,
            # Returned even when invalid: the size badge needs a number to show
            # while the user is still dragging the box.
            area_sq_mi=round(area, 4),
            max_area_sq_mi=self._limits.max_aoi_sqmi,
            violations=violations,
            estimated_credits=DIAGNOSE_BASE_CREDITS + LADDER_CREDITS,
        )

    # ── Creation ─────────────────────────────────────────────────────────────

    def create(self, request: CreateProjectRequest) -> ProjectResponse:
        """Validate, then persist. Never the other way round."""
        area = geodesic_area_sqmi(exterior_ring(request.aoi))
        raw_violations = validate_aoi(aoi_to_fg(request.aoi), self._limits)

        if raw_violations:
            violations = _to_api_violations(raw_violations)
            first = violations[0]
            raise AoiRejectedError(
                message=first.message,
                code=first.code,  # type: ignore[arg-type]
                field=first.field,
                details={
                    "areaSqMi": round(area, 4),
                    "maxAreaSqMi": self._limits.max_aoi_sqmi,
                    "violationCount": len(violations),
                },
            )

        project = self._repo.create(
            name=request.name,
            city=request.city,
            state=request.state,
            aoi_geojson=aoi_to_geojson_dict(request.aoi),
            area_sqmi=round(area, 3),
        )
        # Read the geometry back rather than echoing the input: what the client
        # receives is then what PostGIS actually stored, so a projection or
        # precision surprise surfaces immediately instead of at the first query.
        stored = self._repo.aoi_geojson(project.id)
        if stored is None:  # pragma: no cover — the row was just written
            raise NotFoundError(message="Project geometry could not be read back.")
        return project_to_response(project, stored)

    # ── Reads ────────────────────────────────────────────────────────────────

    def get(self, project_id: uuid.UUID) -> ProjectResponse:
        project = self._repo.get(project_id)
        if project is None:
            raise NotFoundError(
                message=f"No project with id {project_id}.", field="projectId"
            )
        geometry = self._repo.aoi_geojson(project_id)
        if geometry is None:  # pragma: no cover
            raise NotFoundError(message="Project has no stored geometry.")
        return project_to_response(project, geometry)

    def list(self) -> ListProjectsResponse:
        presets = self._repo.list_presets()
        recent = self._repo.list_recent()

        def build(rows: list[Any]) -> list[ProjectResponse]:
            responses: list[ProjectResponse] = []
            for row in rows:
                geometry = self._repo.aoi_geojson(row.id)
                if geometry is None:
                    # A project with no readable geometry is unusable; skipping it
                    # is better than returning a broken entry, and it is logged so
                    # the gap is visible rather than mysterious.
                    log.warning("project.geometry_missing", project_id=str(row.id))
                    continue
                responses.append(project_to_response(row, geometry))
            return responses

        return ListProjectsResponse(presets=build(presets), recent=build(recent))

    def bounds(self, project_id: uuid.UUID) -> tuple[float, float, float, float]:
        """AOI bounding box, for building a FortyGuard request."""
        bounds = self._repo.aoi_bounds(project_id)
        if bounds is None:
            raise NotFoundError(
                message=f"No project with id {project_id}.", field="projectId"
            )
        return bounds
