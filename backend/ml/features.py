"""The feature vector contract.

One rule dominates this module: **feature order is part of the model.** A model
trained on `[canopy, impervious, …]` and served a vector ordered
`[impervious, canopy, …]` does not fail. It returns confident, plausible, wrong
predictions, and nothing downstream can detect it — the intervals stay narrow, the
map still renders, and a city acts on numbers that describe a different world.

So the order is declared once here, saved with every model artefact, and checked on
load. A mismatch raises rather than predicts.

Missing values are passed through as NaN rather than imputed. LightGBM handles NaN
natively by learning a default split direction, which is strictly better than
substituting a mean: the mean is a fabricated observation, and imputing one tells
the model a tile has average canopy when the truth is that nobody measured it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import structlog

log = structlog.get_logger(__name__)

#: The feature vector, in order. Appending is safe for new models; reordering or
#: removing invalidates every existing artefact, which is why the order is
#: persisted alongside the model and verified on load.
FEATURE_ORDER: Final[tuple[str, ...]] = (
    "canopy_pct",
    "impervious_pct",
    "building_pct",
    "water_pct",
    "grass_shrub_pct",
    "albedo_proxy",
    "openness_proxy",
    "elevation_m",
    "local_relief_m",
    "dist_to_water_m",
    "hour_utc",
    "doy",
    "latitude",
    "district_mean_c",
)

#: Features an intervention can plausibly change. The counterfactual transform is
#: only permitted to touch these — a transform that altered `latitude` or `doy`
#: would be describing a different place or a different day, not an intervention.
MUTABLE_FEATURES: Final[frozenset[str]] = frozenset(
    {
        "canopy_pct",
        "impervious_pct",
        "building_pct",
        "water_pct",
        "grass_shrub_pct",
        "albedo_proxy",
        "openness_proxy",
    }
)

#: Plausible ranges, used for out-of-support detection. Percentages are 0-100;
#: the proxies are normalised 0-1 by their producers.
FEATURE_BOUNDS: Final[dict[str, tuple[float, float]]] = {
    "canopy_pct": (0.0, 100.0),
    "impervious_pct": (0.0, 100.0),
    "building_pct": (0.0, 100.0),
    "water_pct": (0.0, 100.0),
    "grass_shrub_pct": (0.0, 100.0),
    "district_mean_c": (-30.0, 60.0),
    "albedo_proxy": (0.0, 1.0),
    "openness_proxy": (0.0, 1.0),
    "elevation_m": (-100.0, 5000.0),
    "local_relief_m": (0.0, 2000.0),
    "dist_to_water_m": (0.0, 200_000.0),
    "hour_utc": (0.0, 23.0),
    "doy": (1.0, 366.0),
    "latitude": (-90.0, 90.0),
}


class FeatureOrderMismatch(RuntimeError):
    """A model artefact's feature order disagrees with this module's."""


@dataclass(frozen=True, slots=True)
class SupportCheck:
    """Whether a feature vector lies inside what the model can speak to."""

    in_support: bool
    reasons: tuple[str, ...]

    @property
    def reason_text(self) -> str:
        return "; ".join(self.reasons)


def to_vector(features: dict[str, float | None]) -> list[float]:
    """Dict → ordered vector, with missing values as NaN.

    NaN rather than 0.0. Zero is a measurement — 0% canopy means bare ground — and
    substituting it for "unmeasured" tells the model something false about the tile.
    """
    return [
        float("nan") if features.get(name) is None else float(features[name])  # type: ignore[arg-type]
        for name in FEATURE_ORDER
    ]


def to_matrix(rows: list[dict[str, float | None]]) -> list[list[float]]:
    return [to_vector(row) for row in rows]


def assert_feature_order(saved_order: list[str] | tuple[str, ...]) -> None:
    """Verify a loaded artefact matches the current contract.

    Raises rather than warning. A reordered vector produces confident wrong
    predictions that nothing downstream can detect, so continuing is worse than
    stopping.
    """
    if tuple(saved_order) != FEATURE_ORDER:
        expected = set(FEATURE_ORDER)
        saved = set(saved_order)
        raise FeatureOrderMismatch(
            "Model artefact feature order does not match the current contract. "
            f"Missing from artefact: {sorted(expected - saved)}. "
            f"Unknown in artefact: {sorted(saved - expected)}. "
            f"Order differs: {list(saved_order) != list(FEATURE_ORDER)}. "
            "Retrain, or check out the code revision the artefact was built from."
        )


def check_support(
    features: dict[str, float | None],
    *,
    training_ranges: dict[str, tuple[float, float]] | None = None,
    max_missing: int = 4,
) -> SupportCheck:
    """Whether the model can speak to this vector.

    Three ways a vector falls outside support:

    1. **Physically impossible values** — 140% canopy is a data bug, and predicting
       from it launders that bug into a temperature.
    2. **Outside the training range** — the model saw canopy from 0-45% in three
       arid districts; asked about 80% it is extrapolating, and its interval will
       not widen to say so.
    3. **Too much missing at once** — LightGBM handles individual NaNs well, but a
       vector that is mostly NaN is a prediction from almost nothing.

    Rejecting is the honest outcome. A refusal with a reason is information; a
    confident number from an unsupported vector is not.
    """
    reasons: list[str] = []
    missing = 0

    for name in FEATURE_ORDER:
        value = features.get(name)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            missing += 1
            continue

        low, high = FEATURE_BOUNDS[name]
        if not (low <= value <= high):
            reasons.append(
                f"{name} is {value:g}, outside the physically possible "
                f"[{low:g}, {high:g}]"
            )
            continue

        if training_ranges is not None and name in training_ranges:
            train_low, train_high = training_ranges[name]
            if not (train_low <= value <= train_high):
                reasons.append(
                    f"{name} is {value:g}, outside the trained range "
                    f"[{train_low:g}, {train_high:g}]"
                )

    if missing > max_missing:
        reasons.append(
            f"{missing} of {len(FEATURE_ORDER)} features are unmeasured, above the "
            f"limit of {max_missing}"
        )

    return SupportCheck(in_support=not reasons, reasons=tuple(reasons))


def observed_ranges(
    rows: list[dict[str, float | None]],
) -> dict[str, tuple[float, float]]:
    """Min/max per feature across a training set, ignoring missing values.

    Saved with the model so `check_support` can tell extrapolation from
    interpolation at inference time.
    """
    ranges: dict[str, tuple[float, float]] = {}
    for name in FEATURE_ORDER:
        values = [
            float(row[name])  # type: ignore[arg-type]
            for row in rows
            if row.get(name) is not None
            and not (isinstance(row[name], float) and math.isnan(row[name]))  # type: ignore[arg-type]
        ]
        if values:
            ranges[name] = (min(values), max(values))
    return ranges
