"""System schemas — health, readiness, credits.

`CreditStatus.remaining` is `int | None`, and the None is load-bearing. SRS C-10
records that FortyGuard's credits-usage endpoint appears in their docs sidebar but
its path and response schema are not documented in prose, so the true remaining
balance may be unavailable. Reporting a guessed number would be worse than
reporting none: a wrong balance could authorise a call that fails and burns the
demo. When it is None the client shows submissions-against-cap instead.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ApiModel, DataMode

DependencyState = Literal["ok", "down", "skipped"]


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded", "down"]
    version: str
    mode: DataMode
    model_version: str
    #: `skipped` is distinct from `ok`: liveness must stay cheap, so dependencies
    #: it does not probe are reported as unchecked rather than as healthy.
    dependencies: dict[str, DependencyState]


class ReadinessCheck(ApiModel):
    name: str
    state: DependencyState
    detail: str | None = None


class ReadinessResponse(ApiModel):
    ready: bool
    checks: list[ReadinessCheck]


class CreditStatusResponse(ApiModel):
    #: None when the upstream balance is not retrievable (SRS C-10). Never
    #: substituted with an estimate.
    remaining: int | None = None
    #: Calls held back so an exhausted budget cannot break the live demo (P5).
    reserve: int
    #: Our own count of chargeable completions in the last 24 h — the lower bound
    #: that is always available even when `remaining` is not.
    submissions_today: int
    daily_cap: int
    #: False once the reserve is reached. The UI switches to cached and fixture
    #: data with a visible banner rather than failing a request.
    live_analysis_enabled: bool
    mode: DataMode


class CoverageWarning(ApiModel):
    """A known limit of the US coverage pre-filter.

    Surfaced through the API because it is a documented gap rather than a bug to
    be quietly worked around: a rectangular filter that admits Buffalo also admits
    Toronto, which sits south of the 49th parallel between the same meridians.
    """

    message: str = (
        "Coverage is pre-filtered against United States bounding boxes. The filter "
        "is conservative but not exact: a small number of nearby Canadian cities "
        "fall inside the same rectangles and cannot be excluded geometrically."
    )
    affected_examples: list[str] = Field(
        default_factory=lambda: ["Toronto, ON", "Montreal, QC"]
    )
