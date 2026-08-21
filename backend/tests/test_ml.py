"""Tests for the temperature model, its feature contract and counterfactuals.

The synthetic training data here has a *known* structure — temperature rises with
impervious surface and falls with canopy — so the tests can assert the model
recovered the right relationship rather than merely that it produced numbers.

The failures targeted are the silent ones: a reordered feature vector, an
extrapolated prediction wearing a confident interval, an imputed mean standing in
for a missing measurement, and a counterfactual that changed something an
intervention cannot change.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import pytest

from ml.counterfactual import (
    STANDARD_TRANSFORMS,
    FeatureDelta,
    InterventionTransform,
    InvalidTransform,
    apply_transform,
    estimate_delta,
    transform_for_category,
)
from ml.features import (
    FEATURE_ORDER,
    MUTABLE_FEATURES,
    FeatureOrderMismatch,
    assert_feature_order,
    check_support,
    observed_ranges,
    to_vector,
)
from ml.model import (
    ModelNotTrained,
    OutOfSupport,
    Prediction,
    TemperatureModel,
    interval_coverage,
    mean_absolute_error,
    r_squared,
)


def _tile(**overrides: float | None) -> dict[str, float | None]:
    base: dict[str, float | None] = {
        "canopy_pct": 12.0,
        "impervious_pct": 58.0,
        "building_pct": 22.0,
        "water_pct": 1.0,
        "grass_shrub_pct": 7.0,
        "albedo_proxy": 0.18,
        "openness_proxy": 0.65,
        "elevation_m": 330.0,
        "local_relief_m": 12.0,
        "dist_to_water_m": 1_500.0,
        "hour_utc": 22.0,
        "doy": 196.0,
        "latitude": 33.45,
        # The district baseline the tile is measured against. Not fetched:
        # derived from the FortyGuard field, the same way the live pipeline
        # derives it.
        "district_mean_c": 37.0,
    }
    base.update(overrides)
    return base


def _synthetic_set(n: int = 900, seed: int = 7) -> tuple[
    list[dict[str, float | None]], list[float]
]:
    """Rows with a known relationship, so the model can be checked against truth.

    temperature = 38 + 0.06·impervious − 0.05·canopy − 4·albedo + noise
    """
    rng = random.Random(seed)
    rows: list[dict[str, float | None]] = []
    targets: list[float] = []

    for _ in range(n):
        canopy = rng.uniform(0, 45)
        impervious = rng.uniform(10, 90)
        albedo = rng.uniform(0.08, 0.35)
        row = _tile(
            canopy_pct=canopy,
            impervious_pct=impervious,
            albedo_proxy=albedo,
            building_pct=rng.uniform(5, 60),
            grass_shrub_pct=rng.uniform(0, 30),
            openness_proxy=rng.uniform(0.3, 0.9),
        )
        rows.append(row)
        targets.append(
            38.0
            + 0.06 * impervious
            - 0.05 * canopy
            - 4.0 * albedo
            + rng.gauss(0, 0.4)
        )

    return rows, targets


# ═════════════════════════════════════════════════════════════════════════════
# The feature contract
# ═════════════════════════════════════════════════════════════════════════════


def test_vector_follows_the_declared_order() -> None:
    features = _tile()
    vector = to_vector(features)
    assert len(vector) == len(FEATURE_ORDER)
    for index, name in enumerate(FEATURE_ORDER):
        assert vector[index] == features[name]


def test_missing_values_become_nan_not_zero() -> None:
    """Zero is a measurement — 0% canopy is bare ground. NaN is 'unmeasured'.

    Substituting zero tells the model something false about the tile.
    """
    vector = to_vector(_tile(canopy_pct=None))
    assert math.isnan(vector[FEATURE_ORDER.index("canopy_pct")])
    assert 0.0 not in {vector[FEATURE_ORDER.index("canopy_pct")]}


def test_matching_feature_order_is_accepted() -> None:
    assert_feature_order(list(FEATURE_ORDER))


def test_reordered_features_raise_rather_than_predict() -> None:
    """The failure this guard exists for.

    A reordered vector does not error — it returns confident, plausible, wrong
    predictions that nothing downstream can detect.
    """
    swapped = list(FEATURE_ORDER)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    with pytest.raises(FeatureOrderMismatch, match="Order differs"):
        assert_feature_order(swapped)


def test_missing_feature_in_artefact_raises() -> None:
    with pytest.raises(FeatureOrderMismatch, match="Missing from artefact"):
        assert_feature_order(list(FEATURE_ORDER)[:-1])


def test_unknown_feature_in_artefact_raises() -> None:
    with pytest.raises(FeatureOrderMismatch, match="Unknown in artefact"):
        assert_feature_order([*FEATURE_ORDER, "moon_phase"])


# ═════════════════════════════════════════════════════════════════════════════
# Support
# ═════════════════════════════════════════════════════════════════════════════


def test_a_normal_tile_is_in_support() -> None:
    assert check_support(_tile()).in_support


@pytest.mark.parametrize(
    ("feature", "value"),
    [
        ("canopy_pct", 140.0),
        ("canopy_pct", -5.0),
        ("albedo_proxy", 2.5),
        ("hour_utc", 27.0),
        ("doy", 400.0),
    ],
)
def test_physically_impossible_values_are_out_of_support(
    feature: str, value: float
) -> None:
    """Predicting from a data bug launders it into a temperature."""
    result = check_support(_tile(**{feature: value}))
    assert not result.in_support
    assert feature in result.reason_text


def test_values_outside_the_trained_range_are_flagged() -> None:
    """A quantile model's interval does not widen outside its training range."""
    result = check_support(
        _tile(canopy_pct=80.0), training_ranges={"canopy_pct": (0.0, 45.0)}
    )
    assert not result.in_support
    assert "outside the trained range" in result.reason_text


def test_a_mostly_empty_vector_is_out_of_support() -> None:
    sparse = {name: None for name in FEATURE_ORDER}
    result = check_support(sparse)
    assert not result.in_support
    assert "unmeasured" in result.reason_text


def test_a_few_missing_features_are_tolerated() -> None:
    """LightGBM handles individual NaNs natively; refusing them would be wasteful."""
    assert check_support(_tile(local_relief_m=None, water_pct=None)).in_support


def test_observed_ranges_ignore_missing_values() -> None:
    rows = [_tile(canopy_pct=10.0), _tile(canopy_pct=None), _tile(canopy_pct=30.0)]
    ranges = observed_ranges(rows)
    assert ranges["canopy_pct"] == (10.0, 30.0)


# ═════════════════════════════════════════════════════════════════════════════
# Prediction plumbing
# ═════════════════════════════════════════════════════════════════════════════


def test_crossed_quantiles_are_ordered_on_construction() -> None:
    """Independently-fitted quantiles can cross on sparse regions.

    Left alone that produces an interval that does not contain its own estimate.
    """
    prediction = Prediction.from_quantiles(p10=42.0, p50=40.0, p90=38.0)
    assert prediction.low <= prediction.value <= prediction.high


def test_predicting_before_training_raises_a_clear_error() -> None:
    with pytest.raises(ModelNotTrained, match="No model is loaded"):
        TemperatureModel("v0").predict(_tile())


def test_loading_from_an_empty_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(ModelNotTrained, match="No model metadata"):
        TemperatureModel.load(tmp_path)


# ═════════════════════════════════════════════════════════════════════════════
# Metrics
# ═════════════════════════════════════════════════════════════════════════════


def _p(value: float, spread: float = 1.0) -> Prediction:
    return Prediction(value=value, low=value - spread, high=value + spread)


def test_interval_coverage_counts_observations_inside_the_band() -> None:
    predictions = [_p(40.0), _p(40.0), _p(40.0), _p(40.0)]
    actuals = [40.5, 39.5, 44.0, 40.0]  # three inside, one outside
    assert interval_coverage(predictions, actuals) == pytest.approx(0.75)


def test_out_of_support_predictions_are_excluded_from_metrics() -> None:
    """The model declined to speak; penalising the refusal would be wrong."""
    predictions: list[Prediction | None] = [_p(40.0), None, _p(40.0)]
    actuals = [40.2, 99.0, 39.8]
    assert interval_coverage(predictions, actuals) == 1.0
    assert mean_absolute_error(predictions, actuals) == pytest.approx(0.2, abs=1e-9)


def test_r_squared_of_a_degenerate_set_is_zero_not_one() -> None:
    """Every actual identical: R² is undefined, and 1.0 would advertise a fit."""
    predictions = [_p(40.0), _p(40.0), _p(40.0)]
    assert r_squared(predictions, [40.0, 40.0, 40.0]) == 0.0


def test_metrics_on_an_all_refused_batch_are_zero_not_a_crash() -> None:
    predictions: list[Prediction | None] = [None, None]
    assert interval_coverage(predictions, [1.0, 2.0]) == 0.0
    assert mean_absolute_error(predictions, [1.0, 2.0]) == 0.0


# ═════════════════════════════════════════════════════════════════════════════
# Counterfactual transforms
# ═════════════════════════════════════════════════════════════════════════════


def test_a_transform_cannot_change_an_immutable_feature() -> None:
    """Altering latitude describes a different place, not an intervention."""
    with pytest.raises(InvalidTransform, match="not something an intervention"):
        InterventionTransform(
            code="teleport", deltas=(FeatureDelta("latitude", 5.0),)
        )


def test_every_standard_transform_touches_only_mutable_features() -> None:
    for transform in STANDARD_TRANSFORMS.values():
        for delta in transform.deltas:
            assert delta.feature in MUTABLE_FEATURES


def test_applying_a_transform_does_not_mutate_the_input() -> None:
    original = _tile()
    snapshot = dict(original)
    apply_transform(original, transform_for_category("green"))
    assert original == snapshot


def test_planting_raises_canopy_and_lowers_impervious() -> None:
    """Trees do two things, and only a hand-written transform captures the second."""
    result = apply_transform(_tile(canopy_pct=12.0, impervious_pct=58.0),
                             transform_for_category("green"))
    assert result["canopy_pct"] == 27.0
    assert result["impervious_pct"] == 50.0


def test_transforms_clamp_to_feature_bounds() -> None:
    result = apply_transform(_tile(canopy_pct=95.0), transform_for_category("green"))
    assert result["canopy_pct"] == 100.0


def test_a_delta_against_an_unmeasured_feature_is_skipped() -> None:
    """Adding canopy to a tile with unknown canopy would invent both numbers."""
    result = apply_transform(_tile(canopy_pct=None), transform_for_category("green"))
    assert result["canopy_pct"] is None
    # The other deltas in the same transform still apply.
    assert result["impervious_pct"] == 50.0


def test_an_unknown_category_raises() -> None:
    with pytest.raises(InvalidTransform, match="No transform defined"):
        transform_for_category("magic")


# ═════════════════════════════════════════════════════════════════════════════
# End to end — trains a real model
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def trained() -> TemperatureModel:
    pytest.importorskip("lightgbm")
    rows, targets = _synthetic_set()
    model = TemperatureModel("test-1.0")
    model.fit(rows, targets, num_boost_round=120)
    return model


def test_model_recovers_the_known_relationship(trained: TemperatureModel) -> None:
    """More paving is hotter, more canopy is cooler — the structure in the data."""
    paved = trained.predict(_tile(impervious_pct=85.0, canopy_pct=2.0))
    leafy = trained.predict(_tile(impervious_pct=20.0, canopy_pct=40.0))
    assert paved.value > leafy.value


def test_predictions_carry_an_ordered_interval(trained: TemperatureModel) -> None:
    prediction = trained.predict(_tile())
    assert prediction.low <= prediction.value <= prediction.high
    assert prediction.high > prediction.low, "a degenerate interval is not useful"


def test_held_out_accuracy_is_reasonable(trained: TemperatureModel) -> None:
    """Guards against a model that fits nothing — noise σ is 0.4 °C."""
    rows, targets = _synthetic_set(n=200, seed=99)
    predictions = trained.predict_batch(rows)
    assert mean_absolute_error(predictions, targets) < 1.5
    assert r_squared(predictions, targets) > 0.7


def test_learnt_intervals_are_roughly_calibrated(trained: TemperatureModel) -> None:
    """A p10-p90 band should contain about 80% of held-out observations.

    Materially less would mean every interval the product displays is too narrow.
    The band here is generous because the tolerance has to survive a small
    synthetic sample.
    """
    rows, targets = _synthetic_set(n=300, seed=1234)
    coverage = interval_coverage(trained.predict_batch(rows), targets)
    assert 0.55 < coverage < 0.98, f"coverage was {coverage:.2f}"


def test_extrapolation_is_refused_not_answered(trained: TemperatureModel) -> None:
    """Canopy was 0-45% in training; 90% is extrapolation."""
    with pytest.raises(OutOfSupport, match="outside the trained range"):
        trained.predict(_tile(canopy_pct=90.0))


def test_batch_marks_refused_tiles_as_none(trained: TemperatureModel) -> None:
    """The caller needs to know *which* tiles were refused, to show a reason."""
    rows = [_tile(), _tile(canopy_pct=95.0), _tile()]
    results = trained.predict_batch(rows)
    assert results[0] is not None
    assert results[1] is None
    assert results[2] is not None


def test_attribution_identifies_the_dominant_driver(
    trained: TemperatureModel,
) -> None:
    """A heavily paved, treeless tile should be attributed to paving or canopy."""
    contributions = trained.contributions(
        _tile(impervious_pct=88.0, canopy_pct=1.0)
    )
    assert set(contributions) == set(FEATURE_ORDER)
    top = trained.top_driver(_tile(impervious_pct=88.0, canopy_pct=1.0))
    assert top in {"impervious_pct", "canopy_pct", "albedo_proxy"}


def test_counterfactual_planting_cools_a_paved_tile(
    trained: TemperatureModel,
) -> None:
    result = estimate_delta(
        trained,
        _tile(impervious_pct=80.0, canopy_pct=5.0),
        transform_for_category("green"),
    )
    assert result.delta_c < 0, "planting must not warm a paved block"
    assert result.delta_low <= result.delta_c <= result.delta_high


def test_counterfactual_interval_spans_combined_uncertainty(
    trained: TemperatureModel,
) -> None:
    """Pairing worst-case counterfactual with best-case baseline, not midpoints.

    Subtracting midpoints would understate the range.
    """
    result = estimate_delta(
        trained,
        _tile(impervious_pct=70.0, canopy_pct=10.0),
        transform_for_category("green"),
    )
    naive_width = result.counterfactual.value - result.baseline.value
    assert (result.delta_high - result.delta_low) > abs(naive_width)


def test_a_transform_pushing_out_of_support_names_the_intervention(
    trained: TemperatureModel,
) -> None:
    """The UI must be able to say which intervention was refused on which block."""
    with pytest.raises(OutOfSupport, match="green"):
        estimate_delta(
            trained, _tile(canopy_pct=44.0), transform_for_category("green")
        )


def test_save_and_load_round_trips(tmp_path: Path, trained: TemperatureModel) -> None:
    trained.save(tmp_path)
    reloaded = TemperatureModel.load(tmp_path)

    assert reloaded.model_version == trained.model_version
    before = trained.predict(_tile())
    after = reloaded.predict(_tile())
    assert after.value == pytest.approx(before.value)
    assert after.low == pytest.approx(before.low)


def test_a_tampered_feature_order_is_rejected_on_load(
    tmp_path: Path, trained: TemperatureModel
) -> None:
    """The saved order is checked, not trusted."""
    import json

    trained.save(tmp_path)
    metadata_path = tmp_path / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["feature_order"] = list(reversed(metadata["feature_order"]))
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(FeatureOrderMismatch):
        TemperatureModel.load(tmp_path)


def test_training_ranges_survive_a_round_trip(
    tmp_path: Path, trained: TemperatureModel
) -> None:
    """Without them, a reloaded model cannot tell extrapolation from interpolation."""
    trained.save(tmp_path)
    reloaded = TemperatureModel.load(tmp_path)
    with pytest.raises(OutOfSupport, match="outside the trained range"):
        reloaded.predict(_tile(canopy_pct=90.0))
