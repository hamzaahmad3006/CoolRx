"""Pre-flight validation for FortyGuard requests.

Pure functions, no I/O, exhaustively unit-tested. This is the most important
module in the client.

Why it earns that status: FortyGuard does **not** charge credits for requests it
rejects (400/422), but does charge for every request it completes. Validating
locally is therefore free credit protection — and it means a malformed request
never reaches the network (SRS FR-002, FR-023).

Every rule here traces to FortyGuard's published Known Limitations page.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from pyproj import Geod

from .models import (
    AoiFeatureCollection,
    DateTimeSpec,
    EnvParameter,
    HeatmapRequest,
)

#: WGS84 geodesic calculator — areas must be geodesic, not planar, or a
#: degrees-squared approximation would misjudge the cap by latitude.
_GEOD = Geod(ellps="WGS84")

SQ_METRES_PER_SQ_MILE = 2_589_988.110336

@dataclass(frozen=True, slots=True)
class BoundingBox:
    west: float
    south: float
    east: float
    north: float

    def contains(self, lon: float, lat: float) -> bool:
        return self.west <= lon <= self.east and self.south <= lat <= self.north


#: Coverage pre-filter: three regional boxes rather than one continental
#: rectangle.
#:
#: ⚠️ What this does and does NOT promise.
#:
#: FortyGuard covers United States locations only, so a non-US AOI wastes a round
#: trip. This filter catches gross errors cheaply — wrong hemisphere, Europe,
#: Asia, South America, Mexico, the Caribbean.
#:
#: It CANNOT enforce "United States". A single generous rectangle was tried first
#: and accepted Toronto, Montreal, Vancouver, Mexico City and Havana. Splitting
#: into regional boxes fixes most of that, but no axis-aligned rectangle can
#: separate southern Ontario from western New York — Toronto (43.65°N, 79.38°W)
#: sits south of the 49th parallel and between the same meridians as Buffalo
#: (42.89°N, 78.88°W). A southern-Ontario or southern-Quebec AOI will therefore
#: still pass this check and be rejected by the API instead.
#:
#: The API is authoritative for border cases. This is a cheap pre-filter, and it
#: is documented as such rather than overstated.
US_REGION_BOXES: tuple[BoundingBox, ...] = (
    # Contiguous 48. North bound just past the 49th-parallel border, so US border
    # towns pass while Vancouver (49.28°N) does not.
    BoundingBox(west=-125.0, south=24.4, east=-66.9, north=49.05),
    # Alaska.
    BoundingBox(west=-172.5, south=51.0, east=-129.0, north=71.5),
    # Hawaii.
    BoundingBox(west=-160.6, south=18.8, east=-154.7, north=22.3),
)


def in_us_coverage(lon: float, lat: float) -> bool:
    """Whether a coordinate falls inside any covered region box."""
    return any(box.contains(lon, lat) for box in US_REGION_BOXES)

#: Reject pathological polygons before they reach the API.
MAX_AOI_VERTICES = 200

#: Documented cap for filter_type 2.
MAX_FILTER_TYPE_2_HOURS = 23


class ViolationCode(StrEnum):
    AOI_AREA_EXCEEDED = "AOI_AREA_EXCEEDED"
    AOI_OUTSIDE_COVERAGE = "AOI_OUTSIDE_COVERAGE"
    AOI_NOT_CLOSED = "AOI_NOT_CLOSED"
    AOI_INVALID_GEOMETRY = "AOI_INVALID_GEOMETRY"
    AOI_TOO_MANY_VERTICES = "AOI_TOO_MANY_VERTICES"
    COORDINATE_OUT_OF_RANGE = "COORDINATE_OUT_OF_RANGE"
    GRANULARITY_INVALID = "GRANULARITY_INVALID"
    FILTER_TYPE_INVALID = "FILTER_TYPE_INVALID"
    DATE_BELOW_FLOOR = "DATE_BELOW_FLOOR"
    DATE_BEYOND_FORECAST = "DATE_BEYOND_FORECAST"
    DATE_MALFORMED = "DATE_MALFORMED"
    START_TIME_REQUIRED = "START_TIME_REQUIRED"
    END_TIME_REQUIRED = "END_TIME_REQUIRED"
    TIME_RANGE_TOO_LONG = "TIME_RANGE_TOO_LONG"
    ENV_PARAMETER_LIMIT = "ENV_PARAMETER_LIMIT"
    THRESHOLD_NOT_APPLICABLE = "THRESHOLD_NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class Violation:
    code: ViolationCode
    message: str
    field: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    violations: tuple[Violation, ...]

    @property
    def is_valid(self) -> bool:
        return len(self.violations) == 0

    def raise_if_invalid(self) -> None:
        from .errors import FortyGuardValidationError

        if not self.is_valid:
            detail = "; ".join(f"{v.code}: {v.message}" for v in self.violations)
            raise FortyGuardValidationError(f"Pre-flight validation failed — {detail}")


@dataclass(frozen=True, slots=True)
class ValidationLimits:
    """Plan-dependent limits, injected so tests need no settings object."""

    max_aoi_sqmi: float = 10.0
    date_floor: date = date(2021, 1, 1)
    max_forecast_hours: int = 12
    granularity_options: tuple[int, ...] = (60, 80, 100)
    max_env_parameters: int | None = 3


# ─────────────────────────────────────────────────────────────────────────────
# Geometry
# ─────────────────────────────────────────────────────────────────────────────


def geodesic_area_sqmi(ring: list[list[float]]) -> float:
    """Geodesic area of a closed ring, in square miles."""
    lons = [point[0] for point in ring]
    lats = [point[1] for point in ring]
    area_m2, _perimeter = _GEOD.polygon_area_perimeter(lons, lats)
    return abs(area_m2) / SQ_METRES_PER_SQ_MILE


def validate_aoi(
    aoi: AoiFeatureCollection, limits: ValidationLimits
) -> list[Violation]:
    """Validate the area of interest against every documented constraint."""
    violations: list[Violation] = []

    if len(aoi.features) != 1:
        violations.append(
            Violation(
                ViolationCode.AOI_INVALID_GEOMETRY,
                f"Expected exactly one Polygon feature, got {len(aoi.features)}.",
                "aoi",
            )
        )
        return violations

    geometry = aoi.features[0].geometry
    if len(geometry.coordinates) == 0:
        violations.append(
            Violation(
                ViolationCode.AOI_INVALID_GEOMETRY,
                "Polygon has no linear ring.",
                "aoi",
            )
        )
        return violations

    ring = geometry.coordinates[0]

    if len(ring) < 4:
        violations.append(
            Violation(
                ViolationCode.AOI_INVALID_GEOMETRY,
                f"A closed ring needs at least 4 positions, got {len(ring)}.",
                "aoi",
            )
        )
        return violations

    if len(ring) > MAX_AOI_VERTICES:
        violations.append(
            Violation(
                ViolationCode.AOI_TOO_MANY_VERTICES,
                f"Ring has {len(ring)} vertices; the limit is {MAX_AOI_VERTICES}.",
                "aoi",
            )
        )

    # The API requires a closed ring: first and last coordinates identical.
    if ring[0] != ring[-1]:
        violations.append(
            Violation(
                ViolationCode.AOI_NOT_CLOSED,
                "Ring is not closed — the first and last coordinates must match.",
                "aoi",
            )
        )

    for lon, lat in ((p[0], p[1]) for p in ring):
        if not (-180.0 <= lon <= 180.0) or not (-90.0 <= lat <= 90.0):
            violations.append(
                Violation(
                    ViolationCode.COORDINATE_OUT_OF_RANGE,
                    f"Coordinate ({lon}, {lat}) is outside valid lon/lat ranges.",
                    "aoi",
                )
            )
            break

    outside = [
        (lon, lat)
        for lon, lat in ((p[0], p[1]) for p in ring)
        if not in_us_coverage(lon, lat)
    ]
    if outside:
        violations.append(
            Violation(
                ViolationCode.AOI_OUTSIDE_COVERAGE,
                "Temperature data covers United States locations only; "
                f"{len(outside)} vertex/vertices fall outside coverage.",
                "aoi",
            )
        )

    area = geodesic_area_sqmi(ring)
    if area > limits.max_aoi_sqmi:
        violations.append(
            Violation(
                ViolationCode.AOI_AREA_EXCEEDED,
                f"AOI area {area:.2f} mi² exceeds the {limits.max_aoi_sqmi:g} mi² "
                "limit for the current API plan.",
                "aoi",
            )
        )

    return violations


# ─────────────────────────────────────────────────────────────────────────────
# Date / time
# ─────────────────────────────────────────────────────────────────────────────


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_hhmm(value: str) -> int | None:
    """Return minutes since midnight, or None if malformed."""
    parts = value.split(":")
    if len(parts) != 2:
        return None
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hours <= 23) or not (0 <= minutes <= 59):
        return None
    return hours * 60 + minutes


def validate_date_time(
    spec: DateTimeSpec,
    limits: ValidationLimits,
    *,
    now: datetime | None = None,
) -> list[Violation]:
    """Validate the date/time window.

    `now` is injectable so tests are not time-dependent.
    """
    violations: list[Violation] = []
    current = now or datetime.now(UTC)

    start = _parse_date(spec.start_date)
    if start is None:
        violations.append(
            Violation(
                ViolationCode.DATE_MALFORMED,
                f"start_date '{spec.start_date}' is not a valid YYYY-MM-DD date.",
                "start_date",
            )
        )
        return violations

    if start < limits.date_floor:
        violations.append(
            Violation(
                ViolationCode.DATE_BELOW_FLOOR,
                f"start_date {start.isoformat()} precedes the earliest available "
                f"data ({limits.date_floor.isoformat()}).",
                "start_date",
            )
        )

    # Forecasting is capped at +12 hours beyond the current time.
    horizon = current + timedelta(hours=limits.max_forecast_hours)
    start_minutes = _parse_hhmm(spec.start_time) if spec.start_time else 0
    requested = datetime(
        start.year,
        start.month,
        start.day,
        (start_minutes or 0) // 60,
        (start_minutes or 0) % 60,
        tzinfo=UTC,
    )
    if requested > horizon:
        violations.append(
            Violation(
                ViolationCode.DATE_BEYOND_FORECAST,
                f"Requested time is beyond the {limits.max_forecast_hours}-hour "
                "forecast horizon.",
                "start_date",
            )
        )

    if spec.filter_type in (1, 2) and spec.start_time is None:
        violations.append(
            Violation(
                ViolationCode.START_TIME_REQUIRED,
                f"filter_type {spec.filter_type} requires start_time.",
                "start_time",
            )
        )

    if spec.filter_type == 2:
        if spec.end_time is None:
            violations.append(
                Violation(
                    ViolationCode.END_TIME_REQUIRED,
                    "filter_type 2 requires end_time.",
                    "end_time",
                )
            )
        elif spec.start_time is not None:
            begin = _parse_hhmm(spec.start_time)
            finish = _parse_hhmm(spec.end_time)
            if begin is not None and finish is not None:
                span_hours = (finish - begin) / 60
                if span_hours <= 0 or span_hours > MAX_FILTER_TYPE_2_HOURS:
                    violations.append(
                        Violation(
                            ViolationCode.TIME_RANGE_TOO_LONG,
                            "filter_type 2 supports a positive range of at most "
                            f"{MAX_FILTER_TYPE_2_HOURS} hours "
                            f"(got {span_hours:.1f}).",
                            "end_time",
                        )
                    )

    return violations


# ─────────────────────────────────────────────────────────────────────────────
# Whole-request validators
# ─────────────────────────────────────────────────────────────────────────────


def validate_heatmap_request(
    request: HeatmapRequest,
    limits: ValidationLimits,
    *,
    now: datetime | None = None,
) -> ValidationResult:
    """Validate a heatmap submission before it can consume a credit."""
    violations: list[Violation] = []
    violations.extend(validate_aoi(request.polygon_aoi, limits))
    violations.extend(validate_date_time(request.date_time, limits, now=now))

    if request.granularity not in limits.granularity_options:
        options = ", ".join(str(g) for g in limits.granularity_options)
        violations.append(
            Violation(
                ViolationCode.GRANULARITY_INVALID,
                f"granularity must be one of {options} (got {request.granularity}).",
                "granularity",
            )
        )

    # `threshold` and `direction` are ignored by tcm and time_of_measure. Sending
    # them is not an API error, but it silently changes the request hash and so
    # splits the cache — flagged so callers do not fragment their own cache.
    from .models import AnalyticType

    if request.threshold is not None and request.analytic_type in (
        AnalyticType.TCM,
        AnalyticType.TIME_OF_MEASURE,
    ):
        violations.append(
            Violation(
                ViolationCode.THRESHOLD_NOT_APPLICABLE,
                f"threshold is ignored by analytic_type "
                f"'{request.analytic_type}'; omit it so the cache key stays stable.",
                "threshold",
            )
        )

    return ValidationResult(tuple(violations))


def validate_env_parameters(
    parameters: list[EnvParameter] | None, limits: ValidationLimits
) -> ValidationResult:
    """Validate the `analysis` list against the plan's per-request cap.

    API Basic and API Startup are limited to 3 parameters per request; Premium has
    full access.
    """
    if parameters is None or limits.max_env_parameters is None:
        return ValidationResult(())

    if len(parameters) > limits.max_env_parameters:
        return ValidationResult(
            (
                Violation(
                    ViolationCode.ENV_PARAMETER_LIMIT,
                    f"The current plan allows {limits.max_env_parameters} "
                    f"environmental parameters per request (got {len(parameters)}).",
                    "analysis",
                ),
            )
        )

    return ValidationResult(())
