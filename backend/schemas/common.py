"""Shared schema foundations.

Two decisions here shape every other schema module.

**camelCase over the wire.** The frontend contract in `types/api.ts` is camelCase,
so every model serialises with a camelCase alias while still accepting snake_case
input. Python code stays snake_case; only the JSON boundary changes.

**`Estimate` is the only way to express a predicted value.** `ci_low` and
`ci_high` are required and validated to bracket the point estimate, which makes a
bare point estimate unrepresentable in a response — the API-layer counterpart of
the frontend `Estimate` interface and the database's interval CHECK constraints.
The same rule is therefore enforced in three independent layers, because SRS §20.3
forbids ever displaying a prediction without its uncertainty.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

# ═════════════════════════════════════════════════════════════════════════════
# Base models
# ═════════════════════════════════════════════════════════════════════════════


class ApiModel(BaseModel):
    """Base for response models.

    `frozen=True` because a response object is a snapshot: mutating one after
    construction would let a later code path change a number that has already
    been validated.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        frozen=True,
        from_attributes=True,
        ser_json_timedelta="float",
    )


class RequestModel(BaseModel):
    """Base for request models.

    `extra="forbid"` so a typo'd or renamed field is a 422 rather than a value
    silently ignored — a misspelled `equityLambda` would otherwise apply the
    default λ and quietly produce a different plan than the user asked for.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


# ═════════════════════════════════════════════════════════════════════════════
# The Estimate type
# ═════════════════════════════════════════════════════════════════════════════

EstimateUnit = Literal["celsius", "hour", "person_hour", "usd", "people", "count"]


class Estimate(ApiModel):
    """A predicted value with its prediction interval.

    Required fields, deliberately: an `Estimate` that could omit its bounds would
    make the frontend's `<Estimate />` renderer unable to guarantee it shows one.
    """

    value: float = Field(description="Point estimate (p50).")
    ci_low: float = Field(description="Lower prediction bound (p10).")
    ci_high: float = Field(description="Upper prediction bound (p90).")
    unit: EstimateUnit
    model_version: str = Field(description="Model that produced it, for provenance.")

    @model_validator(mode="after")
    def _interval_brackets_value(self) -> Self:
        if not (self.ci_low <= self.value <= self.ci_high):
            raise ValueError(
                f"interval [{self.ci_low}, {self.ci_high}] does not contain "
                f"{self.value}; a point estimate outside its own interval is "
                "incoherent, not merely imprecise"
            )
        return self

    @classmethod
    def from_decimals(
        cls,
        *,
        value: Decimal | float,
        ci_low: Decimal | float,
        ci_high: Decimal | float,
        unit: EstimateUnit,
        model_version: str,
    ) -> Estimate:
        """Build from NUMERIC columns.

        Provided so callers do not scatter `float(...)` conversions across the
        controllers, where a forgotten one becomes a serialisation error.
        """
        return cls(
            value=float(value),
            ci_low=float(ci_low),
            ci_high=float(ci_high),
            unit=unit,
            model_version=model_version,
        )


# ═════════════════════════════════════════════════════════════════════════════
# Error envelope (SRS §17.2)
# ═════════════════════════════════════════════════════════════════════════════

ApiErrorCode = Literal[
    "AOI_AREA_EXCEEDED",
    "AOI_OUTSIDE_COVERAGE",
    "AOI_NOT_CLOSED",
    "AOI_INVALID_GEOMETRY",
    "DATE_OUT_OF_RANGE",
    "GRANULARITY_INVALID",
    "CREDITS_BELOW_RESERVE",
    "RATE_LIMITED",
    "JOB_ALREADY_RUNNING",
    "UPSTREAM_UNAVAILABLE",
    "NOT_FOUND",
    "UNAUTHORIZED",
    "VALIDATION_FAILED",
    "INTERNAL_ERROR",
]

#: Detail values are constrained to scalars. A nested object here would tempt
#: callers into shipping model internals or raw upstream payloads to the client.
ErrorDetailValue = str | int | float | bool


class ApiErrorDetail(ApiModel):
    code: ApiErrorCode
    message: str
    field: str | None = None
    details: dict[str, ErrorDetailValue] = Field(default_factory=dict)
    correlation_id: str


class ApiErrorEnvelope(ApiModel):
    """Every non-2xx response body. One shape, so the client has one parser."""

    error: ApiErrorDetail


# ═════════════════════════════════════════════════════════════════════════════
# Provenance (SRS §20.2, principle P2)
# ═════════════════════════════════════════════════════════════════════════════

ProvenanceSourceType = Literal[
    "fortyguard", "derived", "model", "catalog", "external_dataset"
]


class ProvenanceRecord(ApiModel):
    """One figure traced to its origin.

    `value` is a string, not a number: this record reproduces the figure exactly
    as displayed, including its formatting and interval, so the provenance table
    and the report cannot drift apart through separate rounding.
    """

    figure_label: str
    value: str
    source_type: ProvenanceSourceType
    activity_id: str | None = Field(
        default=None, description="FortyGuard handle, where the source is the API."
    )
    source_detail: str
    retrieved_at: datetime


class ProvenanceResponse(ApiModel):
    records: list[ProvenanceRecord]


# ═════════════════════════════════════════════════════════════════════════════
# Shared scalars
# ═════════════════════════════════════════════════════════════════════════════

#: Two-letter US state code. Coverage is United States only.
StateCode = Annotated[str, Field(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")]

#: YYYY-MM-DD.
DateString = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]

#: HH:MM, 24-hour.
TimeString = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]

#: The API accepts only these three, in metres.
Granularity = Literal[60, 80, 100]

#: FortyGuard analytic types.
AnalyticType = Literal["tcm", "exceedance", "persistence", "time_of_measure"]

Direction = Literal["above", "below"]

FilterType = Literal[1, 2, 3]

InterventionCategory = Literal["water", "green", "shade", "material"]

InterventionUnit = Literal["tree", "m2", "structure", "linear_m", "station"]

RiskLevel = Literal["low", "moderate", "high", "extreme"]

PlanObjective = Literal["max_delta_c", "max_person_heat_hours", "equity_weighted"]

#: Includes `cached`: a response served from the request cache is neither live nor
#: a committed fixture, and conflating it with either would misstate the data's
#: origin in the degraded-mode banner (SRS P5).
DataMode = Literal["live", "cached", "fixture"]


# ═════════════════════════════════════════════════════════════════════════════
# Disclaimers
# ═════════════════════════════════════════════════════════════════════════════

#: Attached to every plan and counterfactual response as a required field, so a
#: client cannot render a predicted impact without having received the caveat.
#: SRS principle P4 forbids causal claims; the wording says "estimate" and
#: "assumptions" rather than anything implying a measured effect.
ESTIMATE_DISCLAIMER: str = (
    "Planning-grade estimate under stated assumptions. Values are model "
    "predictions of the temperature field after the listed interventions, not "
    "measurements, and not evidence that an intervention caused a change."
)

#: Shown next to any verification result. The difference-in-differences design
#: reduces confounding but does not eliminate it, and saying so beside the number
#: rather than in a footnote is a requirement, not a courtesy.
VERIFICATION_CAVEAT: str = (
    "Difference-in-differences against untreated control tiles. Weather, land-use "
    "change and measurement conditions differ between the two dates, so this "
    "comparison is evidence consistent with the prediction, not proof of cause."
)

#: Used when the exceedance ladder converts a predicted ΔT into hours avoided.
LADDER_ASSUMPTION: str = (
    "Hours-above-threshold avoided are derived from the exceedance ladder by "
    "assuming a uniform diurnal shift: the predicted ΔT is applied equally across "
    "the day. Real cooling varies by hour, so treat this as an order-of-magnitude "
    "planning figure."
)
