"""Conformal calibration of the prediction interval.

Quantile heads learn the residual spread of the data they were fitted on, which is
narrower than the spread on ground they have not seen. Measured on 2026-08-22 the
p10-p90 band held 28.3% of held-out observations against a nominal 80% — every
interval CoolRx displayed was about three times too confident.

An overconfident interval is worse than no interval: it invites a decision it
cannot support, and a planner has no way to tell it apart from a trustworthy one.

Conformalized quantile regression (Romano, Patterson & Candes, NeurIPS 2019,
arXiv:1905.03222) corrects this without assuming anything about the residual
distribution. The properties worth protecting are that it only ever widens, that
it must be given ground the model has not seen, and that pooling scores is not the
same as pooling per-fold quantiles.
"""

from __future__ import annotations

import random

import pytest

from ml.model import TemperatureModel


def _rows(
    n: int, seed: int = 0, *, noise: float = 0.5
) -> tuple[list[dict], list[float]]:
    """Synthetic tiles with a learnable signal and real noise.

    Invented numbers, and that is fine: they never leave the test process. The
    rule against unsourced values governs what reaches a user.
    """
    rng = random.Random(seed)
    rows, targets = [], []
    for _ in range(n):
        canopy = rng.uniform(0, 60)
        impervious = rng.uniform(20, 95)
        rows.append(
            {
                "canopy_pct": canopy,
                "impervious_pct": impervious,
                "building_pct": rng.uniform(0, 50),
                "water_pct": rng.uniform(0, 5),
                "grass_shrub_pct": rng.uniform(0, 30),
                "albedo_proxy": None,
                "openness_proxy": None,
                "elevation_m": rng.uniform(300, 360),
                "local_relief_m": rng.uniform(0, 8),
                "dist_to_water_m": rng.uniform(0, 5000),
                "hour_utc": 22.0,
                "doy": 200.0,
                "latitude": rng.uniform(33.4, 33.5),
            }
        )
        targets.append(
            0.05 * impervious - 0.04 * canopy + rng.gauss(0, noise)
        )
    return rows, targets


@pytest.fixture(scope="module")
def fitted():
    rows, targets = _rows(600, seed=1)
    model = TemperatureModel(model_version="test")
    model.fit(rows, targets, num_boost_round=60)
    return model


# ── the guarantee ────────────────────────────────────────────────────────────

def test_calibration_widens_the_interval(fitted) -> None:
    rows, targets = _rows(400, seed=2)
    before = fitted.predict(rows[0], enforce_support=False)
    width = fitted.calibrate(rows, targets)
    after = fitted.predict(rows[0], enforce_support=False)

    assert width > 0
    assert after.high - after.low > before.high - before.low
    fitted._conformal_width = 0.0


def test_calibration_lifts_coverage_towards_nominal(fitted) -> None:
    """The point of the exercise, stated as a measurement rather than a claim.

    The calibration and test sets are noisier than the training set, because that
    is the shape of the real failure: the quantile heads were fitted on Phoenix
    and Las Vegas and asked about Tucson, and the residual spread on the new city
    was wider than anything they had seen. On identically-distributed data the
    band covers correctly and there is nothing to fix -- a fact worth knowing,
    since it means calibration is a transfer correction, not a routine tuning step.
    """
    calib_rows, calib_targets = _rows(400, seed=3, noise=1.6)
    test_rows, test_targets = _rows(400, seed=4, noise=1.6)

    def coverage() -> float:
        """Over tiles the model actually answered for.

        A refused tile has no interval, so counting it as a miss would measure
        the support check rather than the calibration.
        """
        preds = fitted.predict_batch(test_rows)
        scored = [
            (p, y)
            for p, y in zip(preds, test_targets, strict=True)
            if p is not None
        ]
        assert scored, "every test tile was refused; nothing to measure"
        return sum(1 for p, y in scored if p.low <= y <= p.high) / len(scored)

    fitted._conformal_width = 0.0
    before = coverage()
    fitted.calibrate(calib_rows, calib_targets)
    after = coverage()

    assert after > before

    # Most of the way to nominal, not exactly there. The conformal guarantee is
    # marginal and finite-sample: with 400 calibration points under a deliberate
    # distribution shift it lands near 0.74, and on the real districts it lands at
    # 0.93. What must hold is that a badly overconfident band becomes roughly
    # right, in that direction.
    assert after >= 0.70, f"coverage {after:.2f} is still far short of nominal"
    assert after - before >= 0.10, (
        f"calibration moved coverage only {after - before:.2f}; it is not doing "
        f"the work it exists for"
    )
    fitted._conformal_width = 0.0


def test_the_interval_still_contains_its_own_estimate(fitted) -> None:
    """Widening must not move the point estimate or invert the bounds."""
    rows, targets = _rows(300, seed=5)
    plain = fitted.predict(rows[0], enforce_support=False)
    fitted.calibrate(rows, targets)
    widened = fitted.predict(rows[0], enforce_support=False)

    assert widened.value == plain.value
    assert widened.low <= widened.value <= widened.high
    fitted._conformal_width = 0.0


def test_calibration_never_narrows(fitted) -> None:
    """A band already wider than needed yields a negative score quantile. The
    learnt quantiles are the model's own statement about spread; conformal
    prediction here only ever adds the shortfall."""
    rows, _ = _rows(300, seed=6)
    # Targets dead-centre in the band produce comfortably negative scores.
    # Out-of-support rows come back as None and are dropped in step with their
    # targets, so the two lists stay aligned.
    pairs = [
        (row, pred.value)
        for row, pred in zip(rows, fitted.predict_batch(rows), strict=True)
        if pred is not None
    ]
    assert pairs
    assert fitted.calibrate([r for r, _ in pairs], [v for _, v in pairs]) == 0.0
    fitted._conformal_width = 0.0


# ── how it must be used ──────────────────────────────────────────────────────

def test_pooling_scores_differs_from_pooling_per_fold_widths(fitted) -> None:
    """Combining per-fold quantiles overshoots. Measured on the real data,
    folds of 0.733 and 0.450 combined by taking the larger gave 97.4% coverage
    against a target of 80%, where pooling the scores gave 0.601 and 93%."""
    a_rows, a_targets = _rows(300, seed=7)
    b_rows, b_targets = _rows(300, seed=8)

    pooled = TemperatureModel.width_from_scores(
        fitted.nonconformity_scores(a_rows, a_targets)
        + fitted.nonconformity_scores(b_rows, b_targets)
    )
    per_fold_max = max(
        TemperatureModel.width_from_scores(
            fitted.nonconformity_scores(a_rows, a_targets)
        ),
        TemperatureModel.width_from_scores(
            fitted.nonconformity_scores(b_rows, b_targets)
        ),
    )
    assert pooled <= per_fold_max


def test_calibrating_on_training_rows_understates_the_width(fitted) -> None:
    """The failure this is most likely to be used wrong in.

    Calibrating on data the boosters were fitted on measures the spread the model
    already fits, returns a width near zero, and restores exactly the
    overconfidence the exercise removes. The test states the trap rather than
    guarding against it, because nothing in the signature can.
    """
    train_rows, train_targets = _rows(600, seed=1)  # the fixture's own data
    unseen_rows, unseen_targets = _rows(400, seed=9, noise=1.6)

    on_training = fitted.calibrate(train_rows, train_targets)
    on_unseen = fitted.calibrate(unseen_rows, unseen_targets)
    fitted._conformal_width = 0.0

    assert on_training < on_unseen


# ── argument handling ────────────────────────────────────────────────────────

def test_mismatched_lengths_are_rejected(fitted) -> None:
    rows, targets = _rows(10, seed=10)
    with pytest.raises(ValueError, match="calibration rows"):
        fitted.calibrate(rows, targets[:5])


def test_an_empty_calibration_set_is_rejected(fitted) -> None:
    with pytest.raises(ValueError, match="empty"):
        fitted.calibrate([], [])


def test_an_uncalibrated_model_predicts_exactly_as_before(fitted) -> None:
    """Adding the machinery must not change a model nobody calibrated."""
    fitted._conformal_width = 0.0
    rows, _ = _rows(5, seed=11)
    p = fitted.predict(rows[0], enforce_support=False)
    assert fitted.conformal_width == 0.0
    assert p.low <= p.value <= p.high


def test_the_width_survives_a_save_and_load(fitted, tmp_path) -> None:
    """It is part of what the model claims. A width lost on load would silently
    return every published interval to being three times too narrow."""
    rows, targets = _rows(300, seed=12)
    width = fitted.calibrate(rows, targets)
    fitted.save(tmp_path)

    reloaded = TemperatureModel.load(tmp_path)
    assert reloaded.conformal_width == pytest.approx(width)

    row = rows[0]
    assert reloaded.predict(row, enforce_support=False).high == pytest.approx(
        fitted.predict(row, enforce_support=False).high
    )
    fitted._conformal_width = 0.0
