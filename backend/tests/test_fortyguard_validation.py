"""Pre-flight validation tests.

These are the most important unit tests in the codebase. FortyGuard does not
charge for requests it rejects but does charge for those it completes, so every
rule verified here is credit protection — and a bug here spends real money.

The suite deliberately asserts the boundary values (exactly 10.00 mi² accepted,
10.01 rejected) rather than comfortable mid-range cases.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from clients.fortyguard.models import (
    AnalyticType,
    AoiFeature,
    AoiFeatureCollection,
    DateTimeSpec,
    EnvParameter,
    HeatmapRequest,
    PolygonGeometry,
    is_missing,
)
from clients.fortyguard.validation import (
    ValidationLimits,
    ViolationCode,
    geodesic_area_sqmi,
    validate_env_parameters,
    validate_heatmap_request,
)

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
LIMITS = ValidationLimits(
    max_aoi_sqmi=10.0,
    date_floor=date(2021, 1, 1),
    max_forecast_hours=12,
    granularity_options=(60, 80, 100),
    max_env_parameters=3,
)


def square_aoi(
    *, center_lon: float = -112.09, center_lat: float = 33.47, half_deg: float = 0.01
) -> AoiFeatureCollection:
    """A closed square ring around a Phoenix-ish centre."""
    w, e = center_lon - half_deg, center_lon + half_deg
    s, n = center_lat - half_deg, center_lat + half_deg
    return AoiFeatureCollection(
        features=[
            AoiFeature(
                geometry=PolygonGeometry(
                    coordinates=[[[w, s], [e, s], [e, n], [w, n], [w, s]]]
                )
            )
        ]
    )


def heatmap(
    *,
    aoi: AoiFeatureCollection | None = None,
    granularity: int = 80,
    start_date: str = "2025-07-15",
    start_time: str | None = "15:00",
    filter_type: int = 1,
    analytic: AnalyticType = AnalyticType.TCM,
    threshold: float | None = None,
) -> HeatmapRequest:
    return HeatmapRequest(
        polygon_aoi=aoi or square_aoi(),
        date_time=DateTimeSpec(
            start_date=start_date,
            start_time=start_time,
            filter_type=filter_type,  # type: ignore[arg-type]
        ),
        granularity=granularity,  # type: ignore[arg-type]
        analytic_type=analytic,
        threshold=threshold,
    )


def codes(request: HeatmapRequest) -> set[ViolationCode]:
    result = validate_heatmap_request(request, LIMITS, now=NOW)
    return {v.code for v in result.violations}


# ── Area ─────────────────────────────────────────────────────────────────────


def test_area_within_cap_is_accepted() -> None:
    assert validate_heatmap_request(heatmap(), LIMITS, now=NOW).is_valid


def test_area_boundary_is_respected() -> None:
    """A ring just inside the cap passes; just outside fails.

    Binary-searching the half-width finds the boundary, which is a stronger
    assertion than picking a comfortable value well inside the limit.
    """
    lo, hi = 0.001, 0.2
    for _ in range(40):
        mid = (lo + hi) / 2
        ring = square_aoi(half_deg=mid).features[0].geometry.coordinates[0]
        if geodesic_area_sqmi(ring) < 10.0:
            lo = mid
        else:
            hi = mid

    assert validate_heatmap_request(
        heatmap(aoi=square_aoi(half_deg=lo)), LIMITS, now=NOW
    ).is_valid
    assert ViolationCode.AOI_AREA_EXCEEDED in codes(
        heatmap(aoi=square_aoi(half_deg=hi * 1.01))
    )


def test_grossly_oversized_area_is_rejected() -> None:
    assert ViolationCode.AOI_AREA_EXCEEDED in codes(
        heatmap(aoi=square_aoi(half_deg=0.5))
    )


# ── Geometry ─────────────────────────────────────────────────────────────────


def test_unclosed_ring_is_rejected() -> None:
    w, e, s, n = -112.10, -112.08, 33.46, 33.48
    aoi = AoiFeatureCollection(
        features=[
            AoiFeature(
                geometry=PolygonGeometry(
                    # Last coordinate does not repeat the first.
                    coordinates=[[[w, s], [e, s], [e, n], [w, n]]]
                )
            )
        ]
    )
    assert ViolationCode.AOI_NOT_CLOSED in codes(heatmap(aoi=aoi))


def test_ring_with_too_few_positions_is_rejected() -> None:
    aoi = AoiFeatureCollection(
        features=[
            AoiFeature(
                geometry=PolygonGeometry(
                    coordinates=[[[-112.1, 33.4], [-112.0, 33.4], [-112.1, 33.4]]]
                )
            )
        ]
    )
    assert ViolationCode.AOI_INVALID_GEOMETRY in codes(heatmap(aoi=aoi))


def test_multiple_features_are_rejected() -> None:
    single = square_aoi().features[0]
    aoi = AoiFeatureCollection(features=[single, single])
    assert ViolationCode.AOI_INVALID_GEOMETRY in codes(heatmap(aoi=aoi))


# ── Coverage ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "lon", "lat"),
    [
        ("London", -0.13, 51.51),
        ("Mexico City", -99.13, 19.43),
        ("Havana", -82.38, 23.11),
        ("Vancouver", -123.12, 49.28),
        ("Sao Paulo", -46.63, -23.55),
    ],
)
def test_out_of_coverage_locations_are_rejected(
    name: str, lon: float, lat: float
) -> None:
    """Coverage is United States only; these must not reach the network."""
    aoi = square_aoi(center_lon=lon, center_lat=lat, half_deg=0.005)
    assert ViolationCode.AOI_OUTSIDE_COVERAGE in codes(heatmap(aoi=aoi)), name


@pytest.mark.parametrize(
    ("name", "lon", "lat"),
    [
        ("Phoenix", -112.09, 33.47),
        ("Buffalo", -78.88, 42.89),
        ("Anchorage", -149.90, 61.22),
        ("Honolulu", -157.86, 21.31),
        ("Seattle", -122.33, 47.61),
    ],
)
def test_in_coverage_locations_are_accepted(name: str, lon: float, lat: float) -> None:
    aoi = square_aoi(center_lon=lon, center_lat=lat, half_deg=0.005)
    assert ViolationCode.AOI_OUTSIDE_COVERAGE not in codes(heatmap(aoi=aoi)), name


def test_known_limitation_southern_ontario_passes_the_prefilter() -> None:
    """Documents a gap rather than hiding it.

    No axis-aligned rectangle can separate southern Ontario from western New
    York: Toronto (43.65°N, 79.38°W) lies south of the 49th parallel and between
    the same meridians as Buffalo (42.89°N, 78.88°W). This AOI therefore passes
    the coverage pre-filter and is rejected by the API instead.

    The test exists so the limitation is recorded and cannot silently regress
    into an unexamined assumption. If it ever starts failing, the filter became
    stricter and this note needs revisiting.
    """
    toronto = square_aoi(center_lon=-79.38, center_lat=43.65, half_deg=0.005)
    assert ViolationCode.AOI_OUTSIDE_COVERAGE not in codes(heatmap(aoi=toronto))


def test_out_of_range_coordinates_are_rejected() -> None:
    aoi = AoiFeatureCollection(
        features=[
            AoiFeature(
                geometry=PolygonGeometry(
                    coordinates=[
                        [[-200.0, 33.4], [-112.0, 33.4], [-112.0, 33.5], [-200.0, 33.4]]
                    ]
                )
            )
        ]
    )
    assert ViolationCode.COORDINATE_OUT_OF_RANGE in codes(heatmap(aoi=aoi))


# ── Granularity ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("granularity", [60, 80, 100])
def test_documented_granularities_are_accepted(granularity: int) -> None:
    assert validate_heatmap_request(
        heatmap(granularity=granularity), LIMITS, now=NOW
    ).is_valid


@pytest.mark.parametrize("granularity", [10, 50, 90, 120, 200])
def test_undocumented_granularities_are_rejected_by_the_model(
    granularity: int,
) -> None:
    """Rejected at model construction, before the validation layer runs.

    `Granularity` is a `Literal[60, 80, 100]`, so pydantic refuses an
    unsupported value earlier and more forcefully than a validation rule could.
    The rule in `validate_heatmap_request` is kept as defence in depth for
    requests assembled from raw dicts, but this is the gate that actually fires.
    """
    with pytest.raises(ValidationError):
        heatmap(granularity=granularity)


def test_granularity_rule_still_catches_dict_sourced_requests() -> None:
    """The validation-layer rule is not dead code.

    A request built by `model_construct` bypasses pydantic validation — which is
    exactly what happens if a payload is ever assembled from an untrusted dict.
    The rule must still catch it.
    """
    request = HeatmapRequest.model_construct(
        polygon_aoi=square_aoi(),
        date_time=DateTimeSpec(start_date="2025-07-15", start_time="15:00", filter_type=1),
        granularity=50,  # type: ignore[arg-type]
        analytic_type=AnalyticType.TCM,
        threshold=None,
    )
    result = validate_heatmap_request(request, LIMITS, now=NOW)
    assert ViolationCode.GRANULARITY_INVALID in {v.code for v in result.violations}


# ── Dates ────────────────────────────────────────────────────────────────────


def test_date_below_floor_is_rejected() -> None:
    """2018 predates coverage under either documented floor."""
    assert ViolationCode.DATE_BELOW_FLOOR in codes(heatmap(start_date="2018-06-01"))


def test_date_between_the_two_documented_floors_is_rejected_conservatively() -> None:
    """2020 is allowed by the API docs (2019 floor) but not by the FAQ (2021).

    The stricter bound is the default until the contradiction is resolved
    empirically, so this must reject rather than gamble a credit.
    """
    assert ViolationCode.DATE_BELOW_FLOOR in codes(heatmap(start_date="2020-06-01"))


def test_date_beyond_forecast_horizon_is_rejected() -> None:
    """The API accepts at most now + 12 hours."""
    assert ViolationCode.DATE_BEYOND_FORECAST in codes(heatmap(start_date="2026-08-25"))


@pytest.mark.parametrize(
    "bad_date", ["15-07-2025", "2025/07/15", "2025-7-15", "July 15 2025", ""]
)
def test_malformed_dates_are_rejected_by_the_model(bad_date: str) -> None:
    """The API requires strict YYYY-MM-DD; pydantic's pattern enforces it first."""
    with pytest.raises(ValidationError):
        heatmap(start_date=bad_date)


def test_date_rule_still_catches_dict_sourced_requests() -> None:
    """Defence in depth for a payload that bypassed model validation."""
    request = HeatmapRequest.model_construct(
        polygon_aoi=square_aoi(),
        date_time=DateTimeSpec.model_construct(
            start_date="15-07-2025", start_time="15:00", filter_type=1
        ),
        granularity=80,
        analytic_type=AnalyticType.TCM,
        threshold=None,
    )
    result = validate_heatmap_request(request, LIMITS, now=NOW)
    assert ViolationCode.DATE_MALFORMED in {v.code for v in result.violations}


def test_filter_type_one_requires_start_time() -> None:
    assert ViolationCode.START_TIME_REQUIRED in codes(
        heatmap(filter_type=1, start_time=None)
    )


# ── Cache-stability guard ────────────────────────────────────────────────────


def test_threshold_on_tcm_is_flagged() -> None:
    """`threshold` is ignored by tcm but still changes the request hash.

    Sending it is not an API error, so nothing upstream complains — but it splits
    the cache and quietly costs credits on what should be a hit.
    """
    assert ViolationCode.THRESHOLD_NOT_APPLICABLE in codes(
        heatmap(analytic=AnalyticType.TCM, threshold=35.0)
    )


def test_threshold_on_exceedance_is_allowed() -> None:
    assert validate_heatmap_request(
        heatmap(analytic=AnalyticType.EXCEEDANCE, threshold=35.0), LIMITS, now=NOW
    ).is_valid


# ── Environmental parameters ─────────────────────────────────────────────────


def test_three_env_parameters_allowed_on_basic() -> None:
    result = validate_env_parameters(
        [
            EnvParameter.HEAT_INDEX_C,
            EnvParameter.WET_BULB_TEMPERATURE_C,
            EnvParameter.RELATIVE_HUMIDITY_PCT,
        ],
        LIMITS,
    )
    assert result.is_valid


def test_four_env_parameters_rejected_on_basic() -> None:
    result = validate_env_parameters(
        [
            EnvParameter.HEAT_INDEX_C,
            EnvParameter.WET_BULB_TEMPERATURE_C,
            EnvParameter.RELATIVE_HUMIDITY_PCT,
            EnvParameter.PRECIPITATION_MM,
        ],
        LIMITS,
    )
    assert not result.is_valid
    assert result.violations[0].code is ViolationCode.ENV_PARAMETER_LIMIT


def test_premium_has_no_env_parameter_cap() -> None:
    premium = ValidationLimits(max_env_parameters=None)
    result = validate_env_parameters(list(EnvParameter), premium)
    assert result.is_valid


# ── Missing values ───────────────────────────────────────────────────────────


def test_missing_values_are_never_zero() -> None:
    """`null` and the legacy -999 both mean missing, never a reading of zero."""
    assert is_missing(None) is True
    assert is_missing(-999) is True
    assert is_missing(0.0) is False
    assert is_missing(35.4) is False
