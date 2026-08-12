"""Tests for the API contract.

The central assertion is that `Estimate` cannot be constructed without a
well-ordered interval, and that no response model offers a way around it. SRS
§20.3 forbids displaying a prediction without its uncertainty, and this is the
layer that makes the violation impossible rather than merely discouraged.

Also checked: camelCase serialisation, since the frontend contract in
`types/api.ts` is camelCase and a silent snake_case response would break every
page at once.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from schemas import (
    ESTIMATE_DISCLAIMER,
    VERIFICATION_CAVEAT,
    AoiFeatureCollection,
    CreatePlanRequest,
    CreateProjectRequest,
    DiagnoseRequest,
    Estimate,
    JobResponse,
    ModelValidationResponse,
    PlanItemResponse,
    PlanResponse,
    PlanTotals,
    TileProperties,
    VerificationResultResponse,
)


def _estimate(**overrides: object) -> Estimate:
    base: dict[str, object] = {
        "value": -1.9,
        "ci_low": -2.6,
        "ci_high": -1.2,
        "unit": "celsius",
        "model_version": "lgbm-2026.08.1",
    }
    base.update(overrides)
    return Estimate(**base)  # type: ignore[arg-type]


# ═════════════════════════════════════════════════════════════════════════════
# Estimate — the interval guarantee
# ═════════════════════════════════════════════════════════════════════════════


def test_estimate_constructs_with_a_valid_interval() -> None:
    est = _estimate()
    assert est.ci_low <= est.value <= est.ci_high


@pytest.mark.parametrize("missing", ["ci_low", "ci_high", "unit", "model_version"])
def test_estimate_requires_every_field(missing: str) -> None:
    """No field is optional. An interval that can be omitted is not a guarantee."""
    payload: dict[str, object] = {
        "value": -1.9,
        "ci_low": -2.6,
        "ci_high": -1.2,
        "unit": "celsius",
        "model_version": "v1",
    }
    del payload[missing]
    with pytest.raises(ValidationError):
        Estimate(**payload)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("low", "value", "high"),
    [
        (-2.6, -3.0, -1.2),  # below the interval
        (-2.6, -0.5, -1.2),  # above the interval
        (-1.2, -1.9, -2.6),  # bounds inverted
        (0.0, 5.0, 1.0),
    ],
)
def test_estimate_rejects_an_incoherent_interval(
    low: float, value: float, high: float
) -> None:
    with pytest.raises(ValidationError, match="does not contain"):
        _estimate(value=value, ci_low=low, ci_high=high)


def test_estimate_allows_a_degenerate_interval() -> None:
    """A zero-width interval is legitimate — an exactly-known value.

    Rejecting it would force callers to fake a spread to satisfy the type.
    """
    est = _estimate(value=0.0, ci_low=0.0, ci_high=0.0)
    assert est.value == est.ci_low == est.ci_high


def test_estimate_rejects_an_unknown_unit() -> None:
    with pytest.raises(ValidationError):
        _estimate(unit="fahrenheit")


def test_estimate_is_frozen() -> None:
    """A validated number must not be mutable afterwards."""
    est = _estimate()
    with pytest.raises(ValidationError):
        est.value = 99.0  # type: ignore[misc]


def test_estimate_from_decimals_accepts_numeric_columns() -> None:
    from decimal import Decimal

    est = Estimate.from_decimals(
        value=Decimal("-1.900"),
        ci_low=Decimal("-2.600"),
        ci_high=Decimal("-1.200"),
        unit="celsius",
        model_version="lgbm-2026.08.1",
    )
    assert est.value == pytest.approx(-1.9)


# ═════════════════════════════════════════════════════════════════════════════
# camelCase over the wire
# ═════════════════════════════════════════════════════════════════════════════


def test_responses_serialise_as_camel_case() -> None:
    """The frontend contract is camelCase; snake_case would break every page."""
    dumped = _estimate().model_dump(by_alias=True)
    assert set(dumped) == {"value", "ciLow", "ciHigh", "unit", "modelVersion"}


def test_requests_accept_camel_case_input() -> None:
    request = CreatePlanRequest.model_validate(
        {"budgetUsd": 250_000, "objective": "equity_weighted", "equityLambda": 1.5}
    )
    assert request.budget_usd == 250_000
    assert request.equity_lambda == 1.5


def test_requests_also_accept_snake_case() -> None:
    """Populate-by-name keeps internal callers and tests from needing aliases."""
    request = CreatePlanRequest.model_validate(
        {"budget_usd": 100.0, "objective": "max_delta_c"}
    )
    assert request.budget_usd == 100.0


def test_nested_models_serialise_as_camel_case() -> None:
    totals = PlanTotals(
        total_cost_usd=1000.0,
        budget_usd=2000.0,
        mean_delta=_estimate(),
        heat_hours_avoided=10.0,
        person_heat_hours_avoided=100.0,
        people_reached=50.0,
    )
    dumped = totals.model_dump(by_alias=True)
    assert "totalCostUsd" in dumped
    assert "ciLow" in dumped["meanDelta"], "nesting must not fall back to snake_case"


# ═════════════════════════════════════════════════════════════════════════════
# Requests reject unknown fields
# ═════════════════════════════════════════════════════════════════════════════


def test_unknown_request_field_is_rejected() -> None:
    """A typo'd field must 422, not be silently ignored.

    A misspelled `equityLambda` that was ignored would apply the default λ and
    return a different plan than the caller asked for, with no error.
    """
    with pytest.raises(ValidationError):
        CreatePlanRequest.model_validate(
            {"budgetUsd": 100.0, "objective": "max_delta_c", "equtyLambda": 3.0}
        )


@pytest.mark.parametrize("budget", [0, -1, -100.5])
def test_non_positive_budget_is_rejected(budget: float) -> None:
    with pytest.raises(ValidationError):
        CreatePlanRequest.model_validate(
            {"budgetUsd": budget, "objective": "max_delta_c"}
        )


@pytest.mark.parametrize("lam", [-0.1, 5.1, 100])
def test_equity_lambda_is_bounded(lam: float) -> None:
    with pytest.raises(ValidationError):
        CreatePlanRequest.model_validate(
            {"budgetUsd": 100.0, "objective": "max_delta_c", "equityLambda": lam}
        )


def test_unknown_objective_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CreatePlanRequest.model_validate(
            {"budgetUsd": 100.0, "objective": "cheapest_first"}
        )


# ═════════════════════════════════════════════════════════════════════════════
# Diagnose request
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("granularity", [30, 50, 70, 120, 0])
def test_invalid_granularity_is_rejected(granularity: int) -> None:
    """The API accepts only 60, 80 and 100 m."""
    with pytest.raises(ValidationError):
        DiagnoseRequest.model_validate(
            {
                "startDate": "2025-07-15",
                "startTime": "15:00",
                "granularity": granularity,
            }
        )


@pytest.mark.parametrize(
    "date", ["2025-7-15", "15-07-2025", "2025/07/15", "", "yesterday"]
)
def test_malformed_date_is_rejected(date: str) -> None:
    with pytest.raises(ValidationError):
        DiagnoseRequest.model_validate({"startDate": date, "startTime": "15:00"})


@pytest.mark.parametrize("time", ["25:00", "15:60", "3:00pm", "1500", ""])
def test_malformed_time_is_rejected(time: str) -> None:
    with pytest.raises(ValidationError):
        DiagnoseRequest.model_validate({"startDate": "2025-07-15", "startTime": time})


def test_ladder_defaults_to_on_but_is_explicit_in_the_payload() -> None:
    """The ladder costs credits, so its state must be visible, not implicit."""
    request = DiagnoseRequest.model_validate(
        {"startDate": "2025-07-15", "startTime": "15:00"}
    )
    assert request.build_ladder is True
    assert "buildLadder" in request.model_dump(by_alias=True)


# ═════════════════════════════════════════════════════════════════════════════
# AOI geometry
# ═════════════════════════════════════════════════════════════════════════════


def _ring() -> list[tuple[float, float]]:
    return [
        (-112.10, 33.40),
        (-112.00, 33.40),
        (-112.00, 33.50),
        (-112.10, 33.50),
        (-112.10, 33.40),
    ]


def _aoi(ring: list[tuple[float, float]] | None = None) -> dict[str, object]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring or _ring()]},
                "properties": {},
            }
        ],
    }


def test_valid_aoi_parses() -> None:
    aoi = AoiFeatureCollection.model_validate(_aoi())
    assert aoi.geometry.type == "Polygon"


def test_unclosed_ring_is_rejected() -> None:
    """An unclosed ring is invalid GeoJSON and would produce wrong PostGIS area."""
    ring = _ring()[:-1]
    with pytest.raises(ValidationError, match="not closed"):
        AoiFeatureCollection.model_validate(_aoi(ring))


def test_ring_with_too_few_positions_is_rejected() -> None:
    ring = [(-112.10, 33.40), (-112.00, 33.40), (-112.10, 33.40)]
    with pytest.raises(ValidationError, match="at least 4"):
        AoiFeatureCollection.model_validate(_aoi(ring))


@pytest.mark.parametrize("count", [0, 2, 3])
def test_aoi_must_contain_exactly_one_feature(count: int) -> None:
    """FortyGuard takes one bounding box, so a multi-feature AOI is ambiguous."""
    payload = _aoi()
    feature = payload["features"][0]  # type: ignore[index]
    payload["features"] = [feature] * count
    with pytest.raises(ValidationError, match="exactly one feature"):
        AoiFeatureCollection.model_validate(payload)


def test_multipolygon_is_rejected() -> None:
    payload = _aoi()
    payload["features"][0]["geometry"]["type"] = "MultiPolygon"  # type: ignore[index]
    with pytest.raises(ValidationError):
        AoiFeatureCollection.model_validate(payload)


@pytest.mark.parametrize("state", ["arizona", "A", "AZX", "az", "1Z"])
def test_state_must_be_a_two_letter_uppercase_code(state: str) -> None:
    with pytest.raises(ValidationError):
        CreateProjectRequest.model_validate(
            {
                "name": "Test",
                "city": "Phoenix",
                "state": state,
                "aoi": _aoi(),
            }
        )


# ═════════════════════════════════════════════════════════════════════════════
# Nulls mean missing, not zero
# ═════════════════════════════════════════════════════════════════════════════


def test_tile_value_may_be_null() -> None:
    """A tile with no measurement must be expressible as null, never as 0."""
    tile = TileProperties(tile_key="9q8yy", value=None, cx=-112.05, cy=33.45)
    assert tile.value is None
    assert tile.model_dump(by_alias=True)["value"] is None


def test_tile_value_zero_is_distinct_from_null() -> None:
    zero = TileProperties(tile_key="9q8yy", value=0.0, cx=0.0, cy=0.0)
    assert zero.value == 0.0 and zero.value is not None


# ═════════════════════════════════════════════════════════════════════════════
# Required disclaimers
# ═════════════════════════════════════════════════════════════════════════════


def _plan_item() -> PlanItemResponse:
    return PlanItemResponse(
        id=uuid.uuid4(),
        rank=1,
        tile_key="9q8yy",
        intervention_code="street_tree_medium",
        intervention_name="Medium street tree",
        category="green",
        quantity=12.0,
        unit="tree",
        unit_cost_usd=450.0,
        cost_usd=5400.0,
        predicted_delta=_estimate(),
        heat_hours_avoided=310.0,
        person_heat_hours_avoided=18400.0,
        people_affected=640.0,
        marginal_benefit_per_usd=3.4,
        rationale=None,
    )


def _plan() -> PlanResponse:
    return PlanResponse(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        budget_usd=10000.0,
        objective="equity_weighted",
        equity_lambda=1.0,
        threshold_c=35.0,
        model_version="lgbm-2026.08.1",
        totals=PlanTotals(
            total_cost_usd=5400.0,
            budget_usd=10000.0,
            mean_delta=_estimate(),
            heat_hours_avoided=310.0,
            person_heat_hours_avoided=18400.0,
            people_reached=640.0,
        ),
        items=[_plan_item()],
        created_at=datetime.now(UTC),
    )


def test_plan_always_carries_the_estimate_disclaimer() -> None:
    """A client rendering a plan has necessarily received the caveat (P4)."""
    dumped = _plan().model_dump(by_alias=True)
    assert dumped["estimateDisclaimer"] == ESTIMATE_DISCLAIMER
    assert dumped["estimateDisclaimer"].strip()


def test_estimate_disclaimer_makes_no_causal_claim() -> None:
    """Principle P4 read literally: the wording must not imply cause."""
    text = ESTIMATE_DISCLAIMER.lower()
    assert "estimate" in text
    assert "not measurements" in text or "not a measurement" in text
    for banned in ("proves", "proven", "will reduce", "caused by"):
        assert banned not in text, f"disclaimer must not contain {banned!r}"


def test_plan_item_rationale_is_optional() -> None:
    """The plan is valid with no LLM prose at all — the model is not load-bearing."""
    item = _plan_item()
    assert item.rationale is None


def test_verification_result_carries_its_caveat_and_names_its_method() -> None:
    result = VerificationResultResponse(
        treated_baseline_c=41.2,
        treated_followup_c=39.0,
        control_baseline_c=40.8,
        control_followup_c=40.5,
        observed_delta_c=-1.9,
        predicted_delta=_estimate(),
        within_ci=True,
        measured_at=datetime.now(UTC),
    )
    assert result.caveat == VERIFICATION_CAVEAT
    assert result.method == "difference_in_differences"


def test_verification_caveat_does_not_claim_proof() -> None:
    text = VERIFICATION_CAVEAT.lower()
    assert "not proof" in text
    for banned in ("proves that", "confirms that", "demonstrates that"):
        assert banned not in text


def test_verification_verdict_field_is_not_named_success() -> None:
    """`within_ci` describes the model's accuracy, not the intervention's merit."""
    fields = set(VerificationResultResponse.model_fields)
    assert "within_ci" in fields
    for banned in ("success", "worked", "effective", "proven"):
        assert banned not in fields


# ═════════════════════════════════════════════════════════════════════════════
# Model card
# ═════════════════════════════════════════════════════════════════════════════


def test_model_validation_requires_at_least_one_limitation() -> None:
    """A model card with no stated limitations is a marketing claim."""
    payload: dict[str, object] = {
        "modelVersion": "lgbm-2026.08.1",
        "trainingTileCount": 50_000,
        "trainingDistricts": ["Phoenix"],
        "heldOutDistricts": ["Las Vegas"],
        "maeC": 0.8,
        "r2": 0.72,
        "intervalCoverage": 0.79,
        "features": ["canopy_pct"],
        "limitations": [],
    }
    with pytest.raises(ValidationError):
        ModelValidationResponse.model_validate(payload)

    payload["limitations"] = ["Trained on three southwestern US districts only."]
    assert ModelValidationResponse.model_validate(payload).limitations


@pytest.mark.parametrize("coverage", [-0.1, 1.1])
def test_interval_coverage_must_be_a_fraction(coverage: float) -> None:
    with pytest.raises(ValidationError):
        ModelValidationResponse.model_validate(
            {
                "modelVersion": "v1",
                "trainingTileCount": 1,
                "trainingDistricts": ["A"],
                "heldOutDistricts": ["B"],
                "maeC": 1.0,
                "r2": 0.5,
                "intervalCoverage": coverage,
                "features": ["x"],
                "limitations": ["y"],
            }
        )


# ═════════════════════════════════════════════════════════════════════════════
# Jobs
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("pct", [-1, 101, 1000])
def test_job_progress_must_be_a_percentage(pct: int) -> None:
    with pytest.raises(ValidationError):
        JobResponse.model_validate(
            {
                "id": str(uuid.uuid4()),
                "projectId": str(uuid.uuid4()),
                "kind": "diagnose",
                "status": "running",
                "stage": "enriching",
                "progressPct": pct,
                "elapsedS": 1.0,
                "error": None,
                "createdAt": datetime.now(UTC).isoformat(),
                "updatedAt": datetime.now(UTC).isoformat(),
            }
        )


def test_degraded_is_a_valid_job_status() -> None:
    """A partial-but-usable run must be expressible as neither success nor failure."""
    job = JobResponse.model_validate(
        {
            "id": str(uuid.uuid4()),
            "projectId": None,
            "kind": "harvest",
            "status": "degraded",
            "stage": "finalizing",
            "progressPct": 100,
            "elapsedS": 42.0,
            "error": "FortyGuard returned 62% tile coverage",
            "createdAt": datetime.now(UTC).isoformat(),
            "updatedAt": datetime.now(UTC).isoformat(),
        }
    )
    assert job.status == "degraded"
    assert job.error is not None
    assert job.project_id is None, "a harvest job is not scoped to a project"
