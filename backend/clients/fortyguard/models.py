"""FortyGuard API request and response models.

⚠️ Every field below is taken verbatim from FortyGuard's published documentation
(Create Heatmap · Environmental Parameters · Check Status · Satellite View
Segmentation · Street View Segmentation · Heat Intelligence · Known Limitations).
No field is invented. Where documentation is silent or self-contradictory the
model is conservative and the gap is noted inline.

Response models use `extra="allow"` on purpose: the API may return fields this
code does not model yet, and dropping them would be worse than carrying them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ─────────────────────────────────────────────────────────────────────────────
# Enumerations — exactly the values the API accepts
# ─────────────────────────────────────────────────────────────────────────────


class AnalyticType(StrEnum):
    """`analytic_type` on POST /v1/heatmap."""

    #: Temperature snapshot; value is °C per tile.
    TCM = "tcm"
    #: Hour of day (0–23, UTC) at which the peak temperature occurs.
    TIME_OF_MEASURE = "time_of_measure"
    #: Number of hours the temperature passes the threshold.
    EXCEEDANCE = "exceedance"
    #: Longest continuous run of hours past the threshold.
    PERSISTENCE = "persistence"


class Direction(StrEnum):
    ABOVE = "above"
    BELOW = "below"


class ActivityStatus(StrEnum):
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    FAILED = "Failed"


#: Documented granularity values, in metres. Anything else is rejected with 400.
Granularity = Literal[60, 80, 100]

#: Filter types. `4` (range of days) appears on the Create Heatmap page but
#: Known Limitations states filter_type "must be 1, 2, or 3" (SRS C-2). Only
#: 1–3 are modelled until verified; `4` is a day-1 verification item.
FilterType = Literal[1, 2, 3]


class EnvParameter(StrEnum):
    """Documented `analysis` values on POST /v1/env_params."""

    HEAT_INDEX_C = "heat_index_celsius"
    APPARENT_TEMPERATURE_C = "apparent_temperature_celsius"
    WET_BULB_TEMPERATURE_C = "wet_bulb_temperature_celsius"
    RELATIVE_HUMIDITY_PCT = "relative_humidity_percent"
    PRECIPITATION_MM = "precipitation_mm"
    CLOUD_COVER_OCTAS = "cloud_cover_octas"
    ELEVATION = "elevation"
    AQI = "air_quality:idx"
    AQI_PM2P5 = "air_quality_pm2p5:idx"
    AQI_PM10 = "air_quality_pm10:idx"
    AQI_NO2 = "air_quality_no2:idx"
    AQI_CO = "aqi_us_co"
    AQI_O3 = "air_quality_o3:idx"
    AQI_SO2 = "air_quality_so2:idx"
    METHANE_PPB = "methane_ppb"
    CO2_PPM = "co2_ppm"
    SOLAR_IRRADIANCE = "solar_irradiance"


#: The three parameters CoolRx requests on API Basic, which caps `analysis` at 3.
BASIC_ENV_PARAMETERS: tuple[EnvParameter, ...] = (
    EnvParameter.HEAT_INDEX_C,
    EnvParameter.WET_BULB_TEMPERATURE_C,
    EnvParameter.RELATIVE_HUMIDITY_PCT,
)

#: Sentinel used by older stored FortyGuard records for a missing value.
#: Treated as missing, NEVER as zero (SRS FR-008).
LEGACY_MISSING = -999


# ─────────────────────────────────────────────────────────────────────────────
# Requests
# ─────────────────────────────────────────────────────────────────────────────


class DateTimeSpec(BaseModel):
    """`date_time` object shared by heatmap, env_params and satellite."""

    model_config = ConfigDict(extra="forbid")

    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    filter_type: FilterType
    #: Required for filter types 1 and 2.
    start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    #: Required for filter type 2; auto-calculated for type 1 (start + 1 hour).
    end_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    #: Auto-populated by the API for filter types 1–3.
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class PolygonGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["Polygon"] = "Polygon"
    #: Linear rings. First and last coordinate must be identical (closed ring).
    coordinates: list[list[Annotated[list[float], Field(min_length=2, max_length=2)]]]


class AoiFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["Feature"] = "Feature"
    properties: dict[str, Any] = Field(default_factory=dict)
    geometry: PolygonGeometry


class AoiFeatureCollection(BaseModel):
    """`polygon_aoi` — a GeoJSON FeatureCollection with a closed Polygon."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[AoiFeature] = Field(min_length=1)


class HeatmapRequest(BaseModel):
    """POST /v1/heatmap."""

    model_config = ConfigDict(extra="forbid")

    polygon_aoi: AoiFeatureCollection
    date_time: DateTimeSpec
    granularity: Granularity
    analytic_type: AnalyticType = AnalyticType.TCM
    #: °C; default 30 per the docs. Ignored by tcm and time_of_measure.
    threshold: float | None = None
    #: For exceedance/persistence only.
    direction: Direction | None = None


class EnvParamsRequest(BaseModel):
    """POST /v1/env_params."""

    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    #: °C for this location, and should match the heatmap that produced it.
    temperature: float
    date_time: DateTimeSpec
    #: Omit to receive all. Basic and Startup are capped at 3 per request.
    analysis: list[EnvParameter] | None = None


class SatelliteLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class SatelliteRequest(BaseModel):
    """POST /v1/satellite — PREMIUM ONLY."""

    model_config = ConfigDict(extra="forbid")

    sat: SatelliteLocation
    date_time: DateTimeSpec
    granularity: Granularity


class StreetViewRequest(BaseModel):
    """POST /v1/streetview — PREMIUM ONLY."""

    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    vertical_angle: float
    horizontal_angle: float = Field(ge=0, le=360)
    back_view: bool = False


class HeatIntelligenceAnalysis(StrEnum):
    GEOGRAPHIC = "geographic"
    ENVIRONMENTAL = "environmental"
    URBAN = "urban"
    EVENTS = "events"
    ANTHROPOGENIC = "anthropogenic"


class HeatIntelligenceRequest(BaseModel):
    """POST /v1/heat_intelligence — PREMIUM ONLY."""

    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    temperature: float
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    analysis: list[HeatIntelligenceAnalysis]


# ─────────────────────────────────────────────────────────────────────────────
# Responses
# ─────────────────────────────────────────────────────────────────────────────


class _Permissive(BaseModel):
    """Base for responses — tolerate fields we do not model yet."""

    model_config = ConfigDict(extra="allow")


class SubmitData(_Permissive):
    activity_id: str


class SubmitEnvelope(_Permissive):
    """Submission response — returns a handle, not a result."""

    error: bool
    status_code: int
    message: str
    data: SubmitData


class TemperatureStats(_Permissive):
    Minimum: float
    Maximum: float
    Mean: float
    Standard_deviation: float


class NormalDistribution(_Permissive):
    x_axis: list[float]
    y_axis: list[float]


class StatsData(_Permissive):
    """`result.stats_data`.

    `units` is `"hour"` for time_of_measure, exceedance and persistence. It must
    be read from here rather than assumed — labelling an hour-valued analytic in
    °C would be a correctness bug (SRS FR-005).
    """

    Temperature_stats: TemperatureStats
    Overall_temperature_distribution: list[float] = Field(default_factory=list)
    Normal_temperature_distribution: NormalDistribution | None = None
    Temperature_frequency: dict[str, float] = Field(default_factory=dict)
    units: str | None = None


class HeatmapResult(_Permissive):
    """`result` on a completed heatmap activity."""

    #: GeoJSON FeatureCollection of tile polygons. Kept loose because tile
    #: properties are parsed by the tile repository, not here.
    map_data: dict[str, Any]
    stats_data: StatsData


class TimeRange(_Permissive):
    start: str
    end: str
    interval: str
    count: int


class EnvMetadata(_Permissive):
    timezone: str
    #: Needed to convert `time_of_measure` UTC hours into district-local time.
    timezone_offset_hours: float
    time_range: TimeRange
    timestamps: list[str] = Field(default_factory=list)


class ClearSkyIrradiance(_Permissive):
    ghi: float
    dni: float
    dhi: float


class SolarIrradiance(_Permissive):
    clear_sky: ClearSkyIrradiance
    description: str | None = None


class EnvLocation(_Permissive):
    lat: float
    lon: float
    elevation: float | None = None
    temperature: float
    #: Time-aligned series per parameter. `None` entries are missing values.
    parameters: dict[str, list[float | None]] = Field(default_factory=dict)
    solar_irradiance: SolarIrradiance | None = None


class EnvParamsResult(_Permissive):
    metadata: EnvMetadata
    locations: list[EnvLocation] = Field(default_factory=list)


class SegmentationBlock(_Permissive):
    """`segmentation` on a satellite response."""

    image_dimensions: dict[str, int] = Field(default_factory=dict)
    mode: str | None = None
    processing_time_seconds: float | None = None
    request_id: str | None = None
    #: Class coverage values, typically percentages.
    segments: dict[str, float] = Field(default_factory=dict)
    #: RGB legend for rendering the mask.
    image_legend: dict[str, Any] = Field(default_factory=dict)
    #: Base64 mask. If the MIME prefix is absent, prepend
    #: `data:image/png;base64,` before rendering in a browser.
    image_content: str | None = None


class SatelliteResult(_Permissive):
    """`result` on a completed satellite activity — PREMIUM ONLY.

    Note `orignal_image`: the field is misspelled in FortyGuard's own API and
    documentation. It is matched verbatim here because matching the actual wire
    format matters more than spelling.
    """

    coordinates: dict[str, str] = Field(default_factory=dict)
    orignal_image: list[str] = Field(default_factory=list)
    image_year: int | None = None
    segmentation: SegmentationBlock | None = None


class HeatIntelligenceResult(_Permissive):
    """`result` on a completed Heat Intelligence activity — PREMIUM ONLY.

    `download_link` is a temporary signed URL. It must be used immediately and
    must never be logged or persisted (a documented FortyGuard requirement).
    """

    download_link: str | None = None


class StatusData(_Permissive):
    activity_id: str
    status: ActivityStatus
    #: Present only when status is Completed. Shape depends on the endpoint.
    result: dict[str, Any] | None = None


class StatusEnvelope(_Permissive):
    """GET /v1/status/{activity_id}."""

    error: bool
    status_code: int
    message: str
    data: StatusData


def is_missing(value: float | None) -> bool:
    """Whether an environmental reading is missing.

    Covers both the current `null` representation and the legacy `-999` sentinel.
    A missing reading must never be interpreted as zero — that would turn "no
    data" into a measurement (SRS FR-008).
    """
    return value is None or value == LEGACY_MISSING
