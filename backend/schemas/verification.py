"""Verification schemas.

This is the module where careless wording would do the most damage. A
before/after temperature difference is not proof that an intervention worked:
weather differs between the two dates, land use changes, and measurement
conditions vary. SRS principle P4 forbids the causal claim outright.

So the schema is built to make the honest reading unavoidable — `caveat` is a
required field, the method is named on every result, and the verdict field is
`within_ci`, which says whether the observation fell inside the predicted
interval, not whether the intervention "worked".
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import (
    VERIFICATION_CAVEAT,
    AnalyticType,
    ApiModel,
    DateString,
    Estimate,
    Granularity,
    RequestModel,
    TimeString,
)

VerificationStatus = Literal["scheduled", "awaiting_followup", "completed", "failed"]


class VerificationProtocolResponse(ApiModel):
    """The measurement plan, publishable before any follow-up exists.

    Issuing the protocol up front is what makes the later comparison credible:
    the treated and control tiles are named in advance, so they cannot be chosen
    after the fact to favour the result.
    """

    plan_id: uuid.UUID
    granularity: Granularity
    start_time: TimeString
    analytic_type: AnalyticType
    scheduled_for: DateString
    treated_tile_keys: list[str]
    #: Untreated tiles matched on baseline temperature and land cover. Without
    #: them a follow-up measures the weather, not the intervention.
    control_tile_keys: list[str]
    statistical_test: Literal["difference_in_differences"] = (
        "difference_in_differences"
    )
    status: VerificationStatus


class VerifyRequest(RequestModel):
    followup_date: DateString
    #: Matching the baseline hour is required for the comparison to mean anything;
    #: it defaults to the protocol's hour rather than to a fixed value.
    followup_time: TimeString | None = None


class VerificationResultResponse(ApiModel):
    treated_baseline_c: float
    treated_followup_c: float
    control_baseline_c: float
    control_followup_c: float
    #: The difference of differences:
    #: (treated_followup − treated_baseline) − (control_followup − control_baseline).
    #: Subtracting the control's change is what removes the shared weather signal.
    observed_delta_c: float
    predicted_delta: Estimate
    #: Whether the observation fell inside the predicted interval. Deliberately
    #: NOT named `success`: a prediction can be correct about a disappointing
    #: outcome, and an observation outside the interval is information about the
    #: model, not a verdict on the intervention.
    within_ci: bool
    method: Literal["difference_in_differences"] = "difference_in_differences"
    #: Required. Rendered adjacent to the number, not in a footnote.
    caveat: str = VERIFICATION_CAVEAT
    measured_at: datetime


class VerificationResponse(ApiModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    protocol: VerificationProtocolResponse
    #: Null until the follow-up measurement has been taken.
    result: VerificationResultResponse | None = None
    created_at: datetime


# ═════════════════════════════════════════════════════════════════════════════
# Model validation (SRS §20.4)
# ═════════════════════════════════════════════════════════════════════════════


class ModelValidationResponse(ApiModel):
    """Published model metrics.

    Exposed through the API and shown on the Methods page rather than kept in a
    notebook: a model whose limitations are documented where users see them is the
    difference between a credible tool and a demo.
    """

    model_version: str
    training_tile_count: int
    training_districts: list[str]
    #: Held out by district, not by random tile split. Neighbouring tiles are
    #: strongly correlated, so a random split would leak and report an
    #: accuracy the model does not have on a new city.
    held_out_districts: list[str]
    mae_c: float
    r2: float
    #: Fraction of held-out observations falling inside p10-p90. Target ≈ 0.80.
    #: A materially lower value means the published intervals are too narrow and
    #: every displayed interval is overconfident.
    interval_coverage: float = Field(ge=0.0, le=1.0)
    features: list[str]
    #: Plain-language limitations. Non-empty by requirement — a model card with no
    #: stated limitations is a marketing claim.
    limitations: list[str] = Field(min_length=1)
