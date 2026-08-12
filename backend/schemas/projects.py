"""Project and AOI schemas.

The AOI is exchanged as a GeoJSON FeatureCollection because that is what MapLibre
produces and what PostGIS consumes. It is typed structurally here rather than as
a free-form dict: an AOI that reaches the validator with the wrong geometry type
has already cost the request a round-trip, and a 422 naming the field is more
useful than a violation code discovered later.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from .common import ApiModel, RequestModel, StateCode

#: A GeoJSON position is [longitude, latitude]. Ordering matters and is a common
#: source of silently-wrong geometry, so it is documented at the type.
Position = tuple[float, float]

#: A polygon ring. GeoJSON requires the first and last position to be identical.
LinearRing = list[Position]


class PolygonGeometry(ApiModel):
    """A GeoJSON Polygon.

    Only Polygon is accepted. MultiPolygon would make the area cap ambiguous —
    FortyGuard takes a single bounding box, so a multi-part AOI cannot be
    submitted as one request.
    """

    type: Literal["Polygon"]
    coordinates: list[LinearRing]

    @model_validator(mode="after")
    def _rings_are_closed(self) -> Self:
        if not self.coordinates:
            raise ValueError("polygon must have at least an exterior ring")
        for index, ring in enumerate(self.coordinates):
            if len(ring) < 4:
                raise ValueError(
                    f"ring {index} has {len(ring)} positions; a closed polygon "
                    "ring needs at least 4"
                )
            if ring[0] != ring[-1]:
                raise ValueError(
                    f"ring {index} is not closed: first position {ring[0]} does "
                    f"not equal last {ring[-1]}"
                )
        return self


class AoiFeature(ApiModel):
    type: Literal["Feature"]
    geometry: PolygonGeometry
    properties: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict
    )


class AoiFeatureCollection(ApiModel):
    type: Literal["FeatureCollection"]
    features: list[AoiFeature]

    @model_validator(mode="after")
    def _exactly_one_feature(self) -> Self:
        if len(self.features) != 1:
            raise ValueError(
                f"AOI must contain exactly one feature, got {len(self.features)}; "
                "FortyGuard takes a single bounding box per request"
            )
        return self

    @property
    def geometry(self) -> PolygonGeometry:
        return self.features[0].geometry


# ═════════════════════════════════════════════════════════════════════════════
# Requests
# ═════════════════════════════════════════════════════════════════════════════


class CreateProjectRequest(RequestModel):
    name: str = Field(min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=120)
    state: StateCode
    aoi: AoiFeatureCollection


class CreateProjectFromPresetRequest(RequestModel):
    preset_id: str = Field(min_length=1)


# ═════════════════════════════════════════════════════════════════════════════
# Responses
# ═════════════════════════════════════════════════════════════════════════════


class ProjectResponse(ApiModel):
    id: uuid.UUID
    name: str
    city: str
    state: str
    aoi: AoiFeatureCollection
    area_sq_mi: float
    is_preset: bool
    created_at: datetime


class ListProjectsResponse(ApiModel):
    presets: list[ProjectResponse]
    recent: list[ProjectResponse]


class PresetSummary(ApiModel):
    """Landing-page card.

    Every number here is a real figure from a completed analytic run on the preset
    district, not marketing copy — which is why the model has no defaults. A
    preset that has not been analysed cannot be advertised.
    """

    preset_id: str
    name: str
    city: str
    state: str
    peak_temp_c: float
    hours_above_threshold: float
    population: float
    thumbnail_url: str


class ListPresetsResponse(ApiModel):
    presets: list[PresetSummary]


# ═════════════════════════════════════════════════════════════════════════════
# AOI validation (SRS FR-002)
# ═════════════════════════════════════════════════════════════════════════════

AoiViolationCode = Literal[
    "AOI_AREA_EXCEEDED",
    "AOI_OUTSIDE_COVERAGE",
    "AOI_NOT_CLOSED",
    "AOI_INVALID_GEOMETRY",
    "DATE_BELOW_FLOOR",
    "DATE_BEYOND_FORECAST",
    "GRANULARITY_INVALID",
    "FILTER_TYPE_INVALID",
]


class AoiViolation(ApiModel):
    code: AoiViolationCode
    message: str
    field: str


class ValidateAoiRequest(RequestModel):
    aoi: AoiFeatureCollection


class ValidateAoiResponse(ApiModel):
    """Pre-flight result.

    Exposed as its own endpoint so the AOI Studio can validate before submitting,
    turning a wasted credit into an inline warning. `area_sq_mi` is returned even
    when invalid, because the size badge needs a number to display while the user
    drags the box.
    """

    is_valid: bool
    area_sq_mi: float
    max_area_sq_mi: float
    violations: list[AoiViolation]
    #: Estimated credits the analysis would consume. Null when not computable —
    #: the ladder's cost depends on how many thresholds are already cached.
    estimated_credits: int | None = None
