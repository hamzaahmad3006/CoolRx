"""Temperature model, attribution and counterfactuals.

LightGBM is imported lazily inside the functions that need it, so this package can
be imported — and its feature contract tested — without the native library present.
"""

from __future__ import annotations

from .counterfactual import (
    STANDARD_TRANSFORMS,
    CounterfactualResult,
    FeatureDelta,
    InterventionTransform,
    InvalidTransform,
    apply_transform,
    estimate_delta,
    transform_for_category,
)
from .features import (
    FEATURE_BOUNDS,
    FEATURE_ORDER,
    MUTABLE_FEATURES,
    FeatureOrderMismatch,
    SupportCheck,
    assert_feature_order,
    check_support,
    observed_ranges,
    to_matrix,
    to_vector,
)
from .model import (
    DEFAULT_PARAMS,
    QUANTILES,
    ModelNotTrained,
    OutOfSupport,
    Prediction,
    TemperatureModel,
    TrainingReport,
    interval_coverage,
    mean_absolute_error,
    r_squared,
)

__all__ = [
    "DEFAULT_PARAMS",
    "FEATURE_BOUNDS",
    "FEATURE_ORDER",
    "MUTABLE_FEATURES",
    "QUANTILES",
    "STANDARD_TRANSFORMS",
    "CounterfactualResult",
    "FeatureDelta",
    "FeatureOrderMismatch",
    "InterventionTransform",
    "InvalidTransform",
    "ModelNotTrained",
    "OutOfSupport",
    "Prediction",
    "SupportCheck",
    "TemperatureModel",
    "TrainingReport",
    "apply_transform",
    "assert_feature_order",
    "check_support",
    "estimate_delta",
    "interval_coverage",
    "mean_absolute_error",
    "observed_ranges",
    "r_squared",
    "to_matrix",
    "to_vector",
    "transform_for_category",
]
