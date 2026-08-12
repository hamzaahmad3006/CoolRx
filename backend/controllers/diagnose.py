"""Diagnose controller — the request side of the analysis pipeline.

This module accepts, validates and enqueues. It does not run the pipeline: that
happens in `workers.tasks`, off the request thread, because a full diagnosis is a
multi-minute job involving up to 14 FortyGuard calls and would time out any
reasonable HTTP client.

The three guards below all exist to protect credits, which are the scarcest
resource in the project:

  1. Date and parameter validation, so a doomed request is never submitted.
  2. A concurrency check, so two identical runs cannot both spend.
  3. A credit-reserve check, so the live demo always has calls left.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import structlog
from sqlalchemy.orm import Session

from clients.fortyguard.models import DateTimeSpec
from clients.fortyguard.validation import validate_date_time
from core.config import Settings
from repositories.fg_cache import FgCacheRepository
from repositories.jobs import DIAGNOSE_STAGES, JobRepository
from repositories.projects import ProjectRepository
from schemas.jobs import DiagnoseRequest, JobAcceptedResponse
from workers.enqueue import EnqueueFailed, enqueue_diagnose

from .errors import (
    CreditsExhaustedError,
    JobAlreadyRunningError,
    NotFoundError,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from .projects import DIAGNOSE_BASE_CREDITS, LADDER_CREDITS, limits_from_settings

log = structlog.get_logger(__name__)


#: Signature of the enqueue boundary, injected so tests need no Redis.
EnqueueDiagnose = Callable[..., str]


class DiagnoseController:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        enqueue: EnqueueDiagnose | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._projects = ProjectRepository(session)
        self._jobs = JobRepository(session)
        self._cache = FgCacheRepository(session)
        self._limits = limits_from_settings(settings)
        self._enqueue = enqueue or enqueue_diagnose

    def start(
        self, project_id: uuid.UUID, request: DiagnoseRequest
    ) -> JobAcceptedResponse:
        if not self._projects.exists(project_id):
            raise NotFoundError(
                message=f"No project with id {project_id}.", field="projectId"
            )

        self._assert_window_valid(request)
        self._assert_no_active_run(project_id)
        self._assert_credits_available(request)

        job = self._jobs.create(kind="diagnose", project_id=project_id)

        # Flush so the row is visible to the worker, which may pick the job up
        # before this request's transaction would otherwise have committed.
        self._session.flush()

        try:
            self._enqueue(
                job_id=job.id,
                project_id=project_id,
                start_date=request.start_date,
                start_time=request.start_time,
                granularity=request.granularity,
                threshold_c=request.threshold_c,
                build_ladder=request.build_ladder,
            )
        except EnqueueFailed as exc:
            # Fail the job now. Leaving it queued with nothing to run it would have
            # the client poll forever on a job that cannot progress.
            self._jobs.fail(
                job.id,
                "Could not reach the job queue, so this analysis was not started. "
                "Redis may be unavailable.",
            )
            raise UpstreamUnavailableError(
                message=(
                    "The analysis queue is unavailable, so this run was not "
                    "started."
                ),
                details={"jobId": str(job.id), "reason": type(exc).__name__},
            ) from exc

        log.info(
            "diagnose.enqueued",
            job_id=str(job.id),
            project_id=str(project_id),
            start_date=request.start_date,
            granularity=request.granularity,
            threshold_c=request.threshold_c,
            build_ladder=request.build_ladder,
        )

        # Stages are returned up front so the client can draw the whole pipeline
        # immediately; discovering them as they arrive would make the progress
        # bar's scale change mid-run.
        return JobAcceptedResponse(
            job_id=job.id,
            stages=[stage for stage, _ in DIAGNOSE_STAGES],
        )

    # ── Guards ───────────────────────────────────────────────────────────────

    def _assert_window_valid(self, request: DiagnoseRequest) -> None:
        """Reject an out-of-range measurement window before spending anything.

        The date floor is contested — the docs say 2019-01-01 and the hackathon FAQ
        says 2021-01-01 (SRS C-1) — so the validator uses the stricter bound from
        configuration. A request below it is refused locally rather than sent to
        find out.
        """
        spec = DateTimeSpec(
            start_date=request.start_date,
            start_time=request.start_time,
            # Filter type 1 — a single hour window, which the API completes to
            # start + 1 hour. This is the only type the diagnosis uses.
            filter_type=1,
        )
        violations = validate_date_time(spec, self._limits)
        if violations:
            first = violations[0]
            raise ValidationFailedError(
                message=first.message,
                code=str(first.code),  # type: ignore[arg-type]
                field=first.field,
                details={"violationCount": len(violations)},
            )

    def _assert_no_active_run(self, project_id: uuid.UUID) -> None:
        active = self._jobs.find_active(project_id=project_id, kind="diagnose")
        if active is not None:
            raise JobAlreadyRunningError(
                message=(
                    "A diagnosis is already running for this project. Wait for it "
                    "to finish rather than starting a second one — both would "
                    "spend credits computing the same thing."
                ),
                details={
                    "jobId": str(active.id),
                    "status": active.status,
                    "progressPct": active.progress_pct,
                },
            )

    def _assert_credits_available(self, request: DiagnoseRequest) -> None:
        """Refuse locally when the run would exceed the daily submission cap.

        This checks **submissions**, not credits. The two are different units and
        must not be compared: `fg_daily_submission_cap` counts API calls per day,
        while `fg_credit_reserve` is a floor on the account's credit balance. The
        credit reserve is enforced inside `FortyGuardClient`, which is the only
        layer that can see the balance — and per SRS C-10 that balance may be
        unavailable, which is exactly why this local submission count exists as an
        independent guard.
        """
        if self._settings.fixture_mode:
            return  # Fixture mode spends nothing.

        needed = DIAGNOSE_BASE_CREDITS + (
            LADDER_CREDITS if request.build_ladder else 0
        )
        used = self._cache.submissions_today()
        cap = self._settings.fg_daily_submission_cap

        if used + needed > cap:
            raise CreditsExhaustedError(
                message=(
                    "This analysis would exceed today's API submission budget. "
                    "Cached and fixture data remain available."
                ),
                details={
                    "needed": needed,
                    "submissionsToday": used,
                    "dailyCap": cap,
                    "remaining": max(0, cap - used),
                },
            )
