"""Job schemas.

`degraded` is a status alongside `completed` and `failed`, not a flag on either. A
run that finished with partial FortyGuard coverage produced usable output and must
say so; folding it into `completed` would hide the caveat, and folding it into
`failed` would throw away a working result (SRS P5).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import ApiModel, DateString, Granularity, RequestModel, TimeString

JobKind = Literal["diagnose", "plan", "verify", "harvest"]
JobStatus = Literal["queued", "running", "completed", "failed", "degraded"]


class DiagnoseRequest(RequestModel):
    start_date: DateString
    start_time: TimeString
    granularity: Granularity = 80
    threshold_c: float = Field(
        default=35.0,
        ge=-50.0,
        le=70.0,
        description="Exceedance threshold in °C.",
    )
    #: Build the 11-step exceedance ladder. Costs up to 11 credits, minus any
    #: threshold already cached, so it is opt-in rather than implicit.
    build_ladder: bool = True


class JobAcceptedResponse(ApiModel):
    """202 body for any job-starting endpoint.

    `stages` is returned up front so the client can render the full pipeline
    outline immediately instead of discovering stages as they arrive, which would
    make the progress bar's scale change mid-run.
    """

    job_id: uuid.UUID
    status: Literal["queued"] = "queued"
    stages: list[str]


class JobResponse(ApiModel):
    id: uuid.UUID
    #: Nullable: a harvest job is not scoped to a project.
    project_id: uuid.UUID | None
    kind: JobKind
    status: JobStatus
    stage: str | None
    progress_pct: int = Field(ge=0, le=100)
    #: Derived from created_at, not stored. The client shows elapsed time; making
    #: it a column would mean writing a row on every tick.
    elapsed_s: float
    #: Carries the failure message when `failed`, and the degradation reason when
    #: `degraded` — a successful-but-partial run explains itself here.
    error: str | None
    created_at: datetime
    updated_at: datetime


class JobProgressEvent(ApiModel):
    """One SSE frame.

    Deliberately not the same shape as `JobResponse`: a progress frame is a delta
    for a live view, and sending the full job on every tick would push identical
    immutable fields dozens of times per run.
    """

    job_id: uuid.UUID
    stage: str
    progress_pct: int = Field(ge=0, le=100)
    message: str
    elapsed_s: float
    status: JobStatus
