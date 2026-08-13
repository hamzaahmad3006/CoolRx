"""Model-based counterfactuals.

Answers "what would this tile's temperature be if we planted trees here?" by
modifying the feature vector and re-running inference. ΔT is the difference from
baseline.

The honest framing, reproduced wherever a resulting figure appears: this is a
**stationarity assumption**, not a simulation. A tile whose canopy is raised to 40%
is assumed to behave like existing tiles that already have 40% canopy and are
otherwise similar. Where canopy correlates with income, irrigation, building age
and street width — which it does everywhere — the model cannot separate canopy's
own effect from its companions. The counterfactual inherits that confound.

Two guards make the failure modes visible rather than silent:

  * **Transforms may only touch mutable features.** Altering latitude or day-of-year
    would describe a different place or date, not an intervention.
  * **The modified vector is support-checked again.** Raising canopy to 80% in a
    district where the model never saw above 45% is extrapolation, and it is
    refused with a reason rather than answered confidently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import structlog

from .features import MUTABLE_FEATURES
from .model import OutOfSupport, Prediction, TemperatureModel

log = structlog.get_logger(__name__)


class InvalidTransform(ValueError):
    """A transform tried to change something an intervention cannot change."""


@dataclass(frozen=True, slots=True)
class FeatureDelta:
    """A change to one feature. Additive, clamped to the feature's bounds."""

    feature: str
    delta: float


@dataclass(frozen=True, slots=True)
class InterventionTransform:
    """How an intervention changes a tile's measured features.

    Deliberately explicit rather than derived from the intervention's category:
    planting trees raises canopy *and* lowers effective impervious surface, and
    only a hand-written transform captures that second effect.
    """

    code: str
    deltas: tuple[FeatureDelta, ...]

    def __post_init__(self) -> None:
        for item in self.deltas:
            if item.feature not in MUTABLE_FEATURES:
                raise InvalidTransform(
                    f"{self.code}: {item.feature!r} is not something an "
                    f"intervention can change. Mutable features are "
                    f"{sorted(MUTABLE_FEATURES)}."
                )


@dataclass(frozen=True, slots=True)
class CounterfactualResult:
    baseline: Prediction
    counterfactual: Prediction
    #: Negative means cooling, matching the convention used everywhere else.
    delta_c: float
    delta_low: float
    delta_high: float


#: Bounds each mutable feature is clamped to after a transform.
_CLAMP: Final[dict[str, tuple[float, float]]] = {
    "canopy_pct": (0.0, 100.0),
    "impervious_pct": (0.0, 100.0),
    "building_pct": (0.0, 100.0),
    "water_pct": (0.0, 100.0),
    "grass_shrub_pct": (0.0, 100.0),
    "albedo_proxy": (0.0, 1.0),
    "openness_proxy": (0.0, 1.0),
}


def apply_transform(
    features: dict[str, float | None], transform: InterventionTransform
) -> dict[str, float | None]:
    """Return a modified copy. The input is never mutated.

    A delta against an **unmeasured** feature is skipped rather than applied to an
    assumed baseline. Adding 15 points of canopy to a tile whose canopy is unknown
    would invent both the starting value and the result.
    """
    modified = dict(features)

    for item in transform.deltas:
        current = modified.get(item.feature)
        if current is None:
            log.debug(
                "counterfactual.skipped_unmeasured",
                intervention=transform.code,
                feature=item.feature,
            )
            continue

        low, high = _CLAMP[item.feature]
        modified[item.feature] = min(max(float(current) + item.delta, low), high)

    return modified


def estimate_delta(
    model: TemperatureModel,
    features: dict[str, float | None],
    transform: InterventionTransform,
) -> CounterfactualResult:
    """ΔT for one intervention on one tile.

    The interval is derived from the two predictions' own bounds rather than by
    subtracting midpoints: `delta_low` pairs the most pessimistic counterfactual
    with the most optimistic baseline, so the reported range spans the genuine
    combined uncertainty instead of understating it.
    """
    baseline = model.predict(features)

    modified = apply_transform(features, transform)
    try:
        counterfactual = model.predict(modified)
    except OutOfSupport as exc:
        # Re-raised with the transform named, so the UI can say which intervention
        # was refused on which tile rather than reporting a generic gap.
        raise OutOfSupport(
            f"{transform.code} moves this block outside the model's trained "
            f"range: {exc}"
        ) from exc

    return CounterfactualResult(
        baseline=baseline,
        counterfactual=counterfactual,
        delta_c=counterfactual.value - baseline.value,
        delta_low=counterfactual.low - baseline.high,
        delta_high=counterfactual.high - baseline.low,
    )


#: Transforms for the standard intervention categories.
#:
#: The magnitudes here describe *land-cover change per unit applied* — geometry,
#: not thermal effect. How much cooling that produces is the model's job, and it is
#: clamped afterwards to the catalog's cited range. Keeping the two separate is
#: what stops an unsourced number entering through the transform.
STANDARD_TRANSFORMS: Final[dict[str, InterventionTransform]] = {
    "green": InterventionTransform(
        code="green",
        deltas=(
            FeatureDelta("canopy_pct", 15.0),
            FeatureDelta("impervious_pct", -8.0),
            FeatureDelta("grass_shrub_pct", 3.0),
        ),
    ),
    "material": InterventionTransform(
        code="material",
        deltas=(FeatureDelta("albedo_proxy", 0.35),),
    ),
    "shade": InterventionTransform(
        code="shade",
        deltas=(
            FeatureDelta("openness_proxy", -0.20),
            FeatureDelta("impervious_pct", -2.0),
        ),
    ),
    "water": InterventionTransform(
        code="water",
        deltas=(
            FeatureDelta("water_pct", 4.0),
            FeatureDelta("grass_shrub_pct", 2.0),
        ),
    ),
}


def transform_for_category(category: str) -> InterventionTransform:
    transform = STANDARD_TRANSFORMS.get(category)
    if transform is None:
        raise InvalidTransform(
            f"No transform defined for category {category!r}; expected one of "
            f"{sorted(STANDARD_TRANSFORMS)}"
        )
    return transform
