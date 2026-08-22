"""Quantile regression for the temperature field, with per-tile attribution.

Three LightGBM models are trained, not one: p10, p50 and p90, each with the
quantile objective. The alternative — one model plus a residual-derived interval —
assumes the residual spread is constant across the feature space, and it is not.
A dense, well-surveyed downtown block is predicted far more confidently than a
sparse industrial edge, and a constant interval would understate uncertainty
exactly where a planner most needs to see it.

The interval is therefore learnt, not assumed, which is what makes
`ModelValidation.interval_coverage` a meaningful check: if the p10-p90 band does not
contain about 80% of held-out observations, the intervals are wrong and the Methods
page says so.

Attribution uses LightGBM's own `pred_contrib=True`, which computes exact TreeSHAP
inside the library. The separate `shap` package is not needed and is not a
dependency — same algorithm, one less thing to install and version-match.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import structlog

from .features import (
    FEATURE_ORDER,
    SupportCheck,
    assert_feature_order,
    check_support,
    observed_ranges,
    to_matrix,
)

log = structlog.get_logger(__name__)

#: The three quantiles. p10/p90 give the ~80% interval the UI displays.
QUANTILES: Final[dict[str, float]] = {"p10": 0.1, "p50": 0.5, "p90": 0.9}

#: Conservative defaults. The training sets here are tens of thousands of rows from
#: a handful of districts, so a deep model would memorise district identity through
#: correlated features rather than learn urban form.
DEFAULT_PARAMS: Final[dict[str, Any]] = {
    "objective": "quantile",
    "metric": "quantile",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "min_data_in_leaf": 40,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "verbosity": -1,
}


def _as_array(rows: list[dict[str, float | None]]) -> Any:
    """Feature dicts → a float64 ndarray for LightGBM.

    numpy is imported here rather than at module scope so `features.py` and its
    tests stay free of the dependency; the conversion happens only at the boundary
    where the native library actually requires it. float64 is explicit because a
    ragged list would otherwise produce an object array and LightGBM's error for
    that names the wrong problem.
    """
    import numpy as np

    return np.asarray(to_matrix(rows), dtype=np.float64)


class ModelNotTrained(RuntimeError):
    """Inference was attempted before a model was loaded or fitted."""


class OutOfSupport(ValueError):
    """The feature vector lies outside what the model can speak to."""


@dataclass(frozen=True, slots=True)
class Prediction:
    """One prediction with its learnt interval.

    Bounds are ordered on construction. Quantile models are fitted independently
    and can cross on sparse regions — p90 landing below p50 — which would otherwise
    produce an interval that does not contain its own estimate.
    """

    value: float
    low: float
    high: float

    @staticmethod
    def from_quantiles(p10: float, p50: float, p90: float) -> Prediction:
        low = min(p10, p50, p90)
        high = max(p10, p50, p90)
        return Prediction(value=p50, low=low, high=high)


@dataclass(slots=True)
class TrainingReport:
    model_version: str
    training_rows: int
    held_out_rows: int
    mae_c: float
    r2: float
    interval_coverage: float
    training_districts: list[str] = field(default_factory=list)
    held_out_districts: list[str] = field(default_factory=list)

    @property
    def intervals_are_calibrated(self) -> bool:
        """Within 5 points of the 80% a p10-p90 band should contain."""
        return abs(self.interval_coverage - 0.8) <= 0.05


class TemperatureModel:
    """Three quantile boosters behind one interface."""

    def __init__(self, model_version: str) -> None:
        self.model_version = model_version
        self._boosters: dict[str, Any] = {}
        self._training_ranges: dict[str, tuple[float, float]] = {}
        #: Conformal half-width in the target's units, added to each side of
        #: the learnt band. Zero until `calibrate` runs, so an uncalibrated
        #: model reports exactly what it did before.
        self._conformal_width: float = 0.0

    # ── Training ─────────────────────────────────────────────────────────────

    def fit(
        self,
        rows: list[dict[str, float | None]],
        targets: list[float],
        *,
        num_boost_round: int = 400,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Fit all three quantiles on the same features."""
        import lightgbm as lgb

        if len(rows) != len(targets):
            raise ValueError(
                f"{len(rows)} feature rows against {len(targets)} targets"
            )
        if not rows:
            raise ValueError("cannot fit on an empty training set")

        matrix = _as_array(rows)
        self._training_ranges = observed_ranges(rows)

        for name, alpha in QUANTILES.items():
            config = {**DEFAULT_PARAMS, **(params or {}), "alpha": alpha}
            dataset = lgb.Dataset(
                matrix, label=targets, feature_name=list(FEATURE_ORDER)
            )
            self._boosters[name] = lgb.train(
                config, dataset, num_boost_round=num_boost_round
            )

        log.info(
            "model.fitted",
            model_version=self.model_version,
            rows=len(rows),
            quantiles=list(QUANTILES),
        )

    def nonconformity_scores(
        self, rows: list[dict[str, float | None]], targets: list[float]
    ) -> list[float]:
        """How far outside the learnt band each observation fell.

            E = max(low - y, y - high)

        Negative when the point sat comfortably inside. Exposed separately from
        `calibrate` so a cross-validated caller can pool the raw scores from
        several folds and take a single quantile of the pooled set, rather than a
        quantile per fold and then a summary of those. Combining per-fold
        quantiles is not equivalent and overshoots: measured on 2026-08-22, folds
        of 0.733 and 0.450 combined by taking the larger produced 97.4% coverage
        against a target of 80%.
        """
        import numpy as np

        self._require_boosters()
        matrix = _as_array(rows)
        per_quantile = [
            booster.predict(matrix) for booster in self._boosters.values()
        ]
        low = np.minimum.reduce(per_quantile)
        high = np.maximum.reduce(per_quantile)
        actual = np.asarray(targets, dtype="float64")
        return [float(v) for v in np.maximum(low - actual, actual - high)]

    @staticmethod
    def width_from_scores(scores: list[float], *, coverage: float = 0.80) -> float:
        """The conformal half-width implied by a pooled set of scores."""
        import numpy as np

        if not scores:
            raise ValueError("cannot calibrate on an empty set")
        n = len(scores)
        level = min(1.0, coverage * (n + 1) / n)
        return max(0.0, float(np.quantile(scores, level, method="higher")))

    def calibrate(
        self,
        rows: list[dict[str, float | None]],
        targets: list[float],
        *,
        coverage: float = 0.80,
    ) -> float:
        """Widen the interval until it earns its nominal coverage.

        Conformalized quantile regression, after Romano, Patterson and Candes,
        "Conformalized Quantile Regression", NeurIPS 2019 (arXiv:1905.03222).

        Quantile heads learn the residual spread of the data they were fitted on.
        Measured on 2026-08-22 the p10-p90 band held 28.3% of held-out
        observations rather than 80%: every interval CoolRx displayed was about
        three times too confident, and an overconfident range is worse than no
        range because it invites a decision it cannot support.

        The correction is distribution-free and assumes nothing about the
        residuals. Score each calibration point by how far outside the band it
        fell,

            E = max(low - y, y - high)

        which is negative when the point sat comfortably inside. Take the
        (1-alpha)(n+1)/n empirical quantile of those scores and add it to both
        sides. The finite-sample term is what makes this a guarantee rather than
        a heuristic.

        The calibration set must be ground the boosters did not see. Passing
        training rows here would measure the spread the model already fits and
        return a width near zero, restoring exactly the overconfidence this
        exists to remove.
        """
        import numpy as np

        self._require_boosters()
        if len(rows) != len(targets):
            raise ValueError(
                f"{len(rows)} calibration rows against {len(targets)} targets"
            )
        if not rows:
            raise ValueError("cannot calibrate on an empty set")

        scores = np.asarray(self.nonconformity_scores(rows, targets))
        n = len(scores)
        # Clipped because at very small n the corrected level can exceed 1.
        level = min(1.0, coverage * (n + 1) / n)
        width = float(np.quantile(scores, level, method="higher"))

        # A negative score quantile means the band was already wider than needed.
        # Narrowing it is not what this is for: the learnt quantiles are the
        # model's own statement about spread, and conformal prediction here only
        # ever adds the shortfall.
        self._conformal_width = max(0.0, width)

        log.info(
            "model.calibrated",
            calibration_rows=n,
            coverage_target=coverage,
            conformal_width=round(self._conformal_width, 4),
        )
        return self._conformal_width

    @property
    def conformal_width(self) -> float:
        """Half-width added to each side of the learnt band. 0.0 if uncalibrated."""
        return self._conformal_width

    def _widen(self, prediction: Prediction) -> Prediction:
        """Apply the conformal half-width. A no-op on an uncalibrated model."""
        if not self._conformal_width:
            return prediction
        return Prediction(
            value=prediction.value,
            low=prediction.low - self._conformal_width,
            high=prediction.high + self._conformal_width,
        )


    # ── Inference ────────────────────────────────────────────────────────────

    def predict(
        self, features: dict[str, float | None], *, enforce_support: bool = True
    ) -> Prediction:
        """Predict for one tile.

        Raises `OutOfSupport` rather than extrapolating. A quantile model's interval
        does **not** widen helpfully outside its training range — it reports the
        same narrow band it learnt inside, so an extrapolated prediction looks
        exactly as confident as a well-supported one.
        """
        self._require_boosters()

        if enforce_support:
            support = self.support(features)
            if not support.in_support:
                raise OutOfSupport(support.reason_text)

        vector = _as_array([features])
        values = {
            name: float(booster.predict(vector)[0])
            for name, booster in self._boosters.items()
        }
        return self._widen(
            Prediction.from_quantiles(
                values["p10"], values["p50"], values["p90"]
            )
        )

    def predict_batch(
        self, rows: list[dict[str, float | None]]
    ) -> list[Prediction | None]:
        """Predict for many tiles. `None` where a tile is out of support.

        None rather than omission: the caller needs to know *which* tiles were
        refused so the map can show a gap with a reason rather than a hole.
        """
        self._require_boosters()
        if not rows:
            return []

        matrix = _as_array(rows)
        per_quantile = {
            name: booster.predict(matrix)
            for name, booster in self._boosters.items()
        }

        out: list[Prediction | None] = []
        for index, row in enumerate(rows):
            if not self.support(row).in_support:
                out.append(None)
                continue
            out.append(
                self._widen(
                    Prediction.from_quantiles(
                        float(per_quantile["p10"][index]),
                        float(per_quantile["p50"][index]),
                        float(per_quantile["p90"][index]),
                    )
                )
            )
        return out

    def support(self, features: dict[str, float | None]) -> SupportCheck:
        return check_support(features, training_ranges=self._training_ranges or None)

    # ── Attribution ──────────────────────────────────────────────────────────

    def contributions(self, features: dict[str, float | None]) -> dict[str, float]:
        """Per-feature SHAP contributions to the p50 prediction, in °C.

        From LightGBM's `pred_contrib=True`, which is exact TreeSHAP computed inside
        the library. The returned array is one value per feature plus a trailing
        base value (the model's expected output); the base is dropped because it is
        not attributable to any feature.
        """
        self._require_boosters()

        raw = self._boosters["p50"].predict(_as_array([features]), pred_contrib=True)
        row = raw[0]
        # Length is len(features) + 1; the last entry is the base value.
        return {
            name: float(row[index]) for index, name in enumerate(FEATURE_ORDER)
        }

    def top_driver(self, features: dict[str, float | None]) -> str:
        contributions = self.contributions(features)
        return max(contributions, key=lambda name: abs(contributions[name]))

    # ── Persistence ──────────────────────────────────────────────────────────

    def save(self, directory: Path) -> None:
        """Write boosters plus the metadata inference needs to stay honest."""
        self._require_boosters()
        directory.mkdir(parents=True, exist_ok=True)

        for name, booster in self._boosters.items():
            booster.save_model(str(directory / f"{name}.txt"))

        # Feature order is saved *with* the model, not assumed. This is what makes
        # a mismatch detectable rather than silently wrong.
        (directory / "metadata.json").write_text(
            json.dumps(
                {
                    "model_version": self.model_version,
                    "feature_order": list(FEATURE_ORDER),
                    "quantiles": QUANTILES,
                    "conformal_width": self._conformal_width,
                    "training_ranges": {
                        key: list(value)
                        for key, value in self._training_ranges.items()
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        log.info("model.saved", path=str(directory), version=self.model_version)

    @classmethod
    def load(cls, directory: Path) -> TemperatureModel:
        import lightgbm as lgb

        metadata_path = directory / "metadata.json"
        if not metadata_path.exists():
            raise ModelNotTrained(
                f"No model metadata at {metadata_path}. Train one with "
                "`python -m ml.train`."
            )

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert_feature_order(metadata["feature_order"])

        model = cls(model_version=metadata["model_version"])
        model._conformal_width = float(metadata.get("conformal_width", 0.0))
        model._training_ranges = {
            key: (float(value[0]), float(value[1]))
            for key, value in metadata.get("training_ranges", {}).items()
        }

        for name in QUANTILES:
            path = directory / f"{name}.txt"
            if not path.exists():
                raise ModelNotTrained(f"Missing quantile model {path}")
            model._boosters[name] = lgb.Booster(model_file=str(path))

        log.info("model.loaded", path=str(directory), version=model.model_version)
        return model

    def _require_boosters(self) -> None:
        if not self._boosters:
            raise ModelNotTrained(
                "No model is loaded. Call fit(), or load() a saved artefact."
            )


# ═════════════════════════════════════════════════════════════════════════════
# Evaluation
# ═════════════════════════════════════════════════════════════════════════════


def interval_coverage(
    predictions: list[Prediction | None], actuals: list[float]
) -> float:
    """Fraction of observations falling inside their predicted interval.

    The single most important model metric. A p10-p90 band should contain about
    80%; materially less means every interval the product displays is too narrow,
    and every figure is overconfident by the same margin.

    Out-of-support predictions are excluded — the model declined to speak, so
    counting them would penalise it for the refusal that was the correct behaviour.
    """
    pairs = [
        (prediction, actual)
        for prediction, actual in zip(predictions, actuals, strict=True)
        if prediction is not None
    ]
    if not pairs:
        return 0.0
    inside = sum(1 for p, a in pairs if p.low <= a <= p.high)
    return inside / len(pairs)


def mean_absolute_error(
    predictions: list[Prediction | None], actuals: list[float]
) -> float:
    pairs = [
        (prediction, actual)
        for prediction, actual in zip(predictions, actuals, strict=True)
        if prediction is not None
    ]
    if not pairs:
        return 0.0
    return sum(abs(p.value - a) for p, a in pairs) / len(pairs)


def r_squared(predictions: list[Prediction | None], actuals: list[float]) -> float:
    pairs = [
        (prediction, actual)
        for prediction, actual in zip(predictions, actuals, strict=True)
        if prediction is not None
    ]
    if len(pairs) < 2:
        return 0.0

    values = [a for _, a in pairs]
    mean = sum(values) / len(values)
    total = sum((a - mean) ** 2 for a in values)
    if total == 0:
        # Every observation identical: R² is undefined, and returning 1.0 would
        # advertise a perfect fit on a degenerate set.
        return 0.0
    residual = sum((p.value - a) ** 2 for p, a in pairs)
    return 1.0 - residual / total
