"""Prescribe controller — plan creation requests and plan reads.

Plan generation is enqueued rather than run inline: it re-runs model inference over
every candidate tile-intervention pair, which is far too slow for a request cycle.

The preconditions are checked here, before a job exists, so the user gets an
immediate actionable message instead of a job that fails 30 seconds later. There are
two, and both are hard:

  1. A diagnosis must have run — there is nothing to plan against otherwise.
  2. The intervention catalog must be populated — every cost and effect size in a
     plan comes from it, and an empty catalog cannot yield a cited plan.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from repositories.jobs import PLAN_STAGES, JobRepository
from repositories.plans import PlanRepository
from repositories.projects import ProjectRepository
from repositories.tables import AnalyticRun, Exposure, InterventionCatalogEntry
from schemas.jobs import JobAcceptedResponse
from schemas.plans import CreatePlanRequest, ListPlansResponse, PlanResponse
from workers.enqueue import EnqueueFailed, enqueue_plan

from .adapters import plan_to_response
from .errors import (
    JobAlreadyRunningError,
    NotFoundError,
    PreconditionMissingError,
    UpstreamUnavailableError,
)

log = structlog.get_logger(__name__)


#: Signature of the enqueue boundary, injected so tests need no Redis.
EnqueuePlan = Callable[..., str]


class PrescribeController:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        enqueue: EnqueuePlan | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._projects = ProjectRepository(session)
        self._plans = PlanRepository(session)
        self._jobs = JobRepository(session)
        self._enqueue = enqueue or enqueue_plan

    # ── Create ───────────────────────────────────────────────────────────────

    def start(
        self, project_id: uuid.UUID, request: CreatePlanRequest
    ) -> JobAcceptedResponse:
        if not self._projects.exists(project_id):
            raise NotFoundError(
                message=f"No project with id {project_id}.", field="projectId"
            )

        threshold = self._resolve_threshold(project_id, request.threshold_c)
        self._assert_catalog_populated()
        self._assert_no_active_run(project_id)

        job = self._jobs.create(kind="plan", project_id=project_id)
        self._session.flush()

        try:
            self._enqueue(
                job_id=job.id,
                project_id=project_id,
                budget_usd=request.budget_usd,
                objective=request.objective,
                equity_lambda=request.equity_lambda,
                threshold_c=threshold,
            )
        except EnqueueFailed as exc:
            self._jobs.fail(
                job.id,
                "Could not reach the job queue, so plan generation was not "
                "started. Redis may be unavailable.",
            )
            raise UpstreamUnavailableError(
                message=(
                    "The analysis queue is unavailable, so this plan was not "
                    "generated."
                ),
                details={"jobId": str(job.id), "reason": type(exc).__name__},
            ) from exc

        log.info(
            "prescribe.enqueued",
            job_id=str(job.id),
            project_id=str(project_id),
            budget_usd=request.budget_usd,
            objective=request.objective,
            equity_lambda=request.equity_lambda,
            threshold_c=threshold,
        )
        return JobAcceptedResponse(
            job_id=job.id, stages=[stage for stage, _ in PLAN_STAGES]
        )

    # ── Reads ────────────────────────────────────────────────────────────────

    def get(self, plan_id: uuid.UUID) -> PlanResponse:
        plan = self._plans.get_with_items(plan_id)
        if plan is None:
            raise NotFoundError(message=f"No plan with id {plan_id}.", field="planId")

        # Re-derive the totals before serving them. A plan whose stored totals
        # drifted from its items would put an unexplainable figure in front of a
        # city, so it is refused rather than displayed.
        ok, reason = self._plans.verify_totals(plan_id)
        if not ok:
            log.error("plan.totals_mismatch", plan_id=str(plan_id), reason=reason)
            raise PreconditionMissingError(
                message=(
                    "This plan's totals do not reconcile with its items and cannot "
                    "be displayed. Regenerate it."
                ),
                details={"planId": str(plan_id), "reason": reason or "unknown"},
            )

        catalog_by_code = {
            row.code: row
            for row in self._session.execute(
                select(InterventionCatalogEntry)
            ).scalars()
        }
        return plan_to_response(
            plan,
            list(plan.items),
            catalog_by_code,
            self._pct_top_svi_quartile(plan.project_id, list(plan.items)),
        )

    def list_for_project(self, project_id: uuid.UUID) -> ListPlansResponse:
        plans = self._plans.list_for_project(project_id)
        return ListPlansResponse(plans=[self.get(plan.id) for plan in plans])

    # ── Guards ───────────────────────────────────────────────────────────────

    def _resolve_threshold(
        self, project_id: uuid.UUID, requested: float | None
    ) -> float:
        """Use the request's threshold, else the project's diagnosis threshold.

        Falling back to a global default would silently plan against a different
        threshold than the diagnosis the user is looking at, making the plan's
        hours-avoided figures incomparable with the map beside them.
        """
        if requested is not None:
            return requested

        stmt = (
            select(AnalyticRun.threshold_c)
            .where(
                AnalyticRun.project_id == project_id,
                AnalyticRun.analytic_type == "exceedance",
                AnalyticRun.threshold_c.is_not(None),
            )
            .order_by(AnalyticRun.created_at.desc())
            .limit(1)
        )
        row = self._session.execute(stmt).first()
        if row is None or row[0] is None:
            raise PreconditionMissingError(
                message=(
                    "No diagnosis has been run for this project, so there is "
                    "nothing to plan against. Run a diagnosis first."
                ),
                field="projectId",
            )
        return float(row[0])

    def _assert_catalog_populated(self) -> None:
        count = self._session.execute(
            select(InterventionCatalogEntry.code).limit(1)
        ).first()
        if count is None:
            raise PreconditionMissingError(
                message=(
                    "The intervention catalog is empty, so no plan can be costed. "
                    "It must be populated from published cost and effect-size "
                    "sources first."
                ),
                details={"remedy": "python -m scripts.load_catalog"},
            )

    def _assert_no_active_run(self, project_id: uuid.UUID) -> None:
        active = self._jobs.find_active(project_id=project_id, kind="plan")
        if active is not None:
            raise JobAlreadyRunningError(
                message="A plan is already being generated for this project.",
                details={
                    "jobId": str(active.id),
                    "status": active.status,
                    "progressPct": active.progress_pct,
                },
            )

    # ── Derived figures ──────────────────────────────────────────────────────

    def _pct_top_svi_quartile(
        self, project_id: uuid.UUID, items: list[object]
    ) -> float | None:
        """Share of reached population living in the most vulnerable SVI quartile.

        Computed on read because the quartile cut is a property of the AOI, not of
        the plan. Returns None rather than 0.0 when SVI coverage is too sparse to
        support the figure — a zero here would read as "this plan reaches nobody
        vulnerable", which is a finding, not a data gap.
        """
        rows = list(
            self._session.execute(
                select(Exposure.tile_key, Exposure.population, Exposure.svi_score).where(
                    Exposure.project_id == project_id,
                    Exposure.svi_score.is_not(None),
                    Exposure.population.is_not(None),
                )
            )
        )
        if len(rows) < 4:
            return None

        scores = sorted(float(row[2]) for row in rows)
        cut = scores[int(0.75 * (len(scores) - 1))]

        treated_keys = {getattr(item, "tile_key", None) for item in items}
        reached_total = 0.0
        reached_top = 0.0
        for tile_key, population, svi in rows:
            if tile_key not in treated_keys:
                continue
            people = float(population)
            reached_total += people
            if float(svi) >= cut:
                reached_top += people

        if reached_total <= 0:
            return None
        return round(reached_top / reached_total, 4)
