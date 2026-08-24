"""RQ job entry points.

Each task owns a job's whole lifecycle: it marks the job running, advances it
through the declared stages, and always reaches a terminal state. The `finally`
discipline matters more than it looks — a task that raised without marking the job
failed would leave the frontend polling a job that will never change, which is
indistinguishable from slow progress.

A job ends in one of three states, and the distinction is load-bearing:

  * **completed** — everything the run promised is present.
  * **degraded** — usable results with something missing, and the reason is stored
    so the UI shows a caveat rather than presenting a gap as complete.
  * **failed** — nothing usable, with a message naming what to do about it.

Nothing here substitutes a plausible value for a missing one. A run without
land-cover data degrades and says so; it does not invent canopy percentages to make
the pipeline appear to have worked.
"""

from __future__ import annotations

import uuid

import structlog

from clients.fortyguard.errors import FortyGuardError
from core.config import get_settings
from repositories.base import session_scope
from repositories.jobs import DIAGNOSE_STAGES, PLAN_STAGES, JobRepository

from .pipeline import PipelineError, run_diagnose_pipeline
from .plan_pipeline import PlanPipelineError, run_plan_pipeline

log = structlog.get_logger(__name__)


def _advance(job_id: uuid.UUID, stage: str, pct: int) -> None:
    with session_scope() as session:
        JobRepository(session).advance(job_id, stage=stage, progress_pct=pct)


def _fail(job_id: uuid.UUID, message: str) -> None:
    with session_scope() as session:
        JobRepository(session).fail(job_id, message)


def _complete(job_id: uuid.UUID) -> None:
    with session_scope() as session:
        JobRepository(session).complete(job_id)


def _degrade(job_id: uuid.UUID, reason: str) -> None:
    with session_scope() as session:
        JobRepository(session).degrade(job_id, reason)


def run_diagnose(
    job_id_str: str,
    project_id_str: str,
    start_date: str,
    start_time: str,
    granularity: int,
    threshold_c: float,
    build_ladder: bool,
) -> None:
    """Execute the diagnosis pipeline.

    Arguments are primitives because RQ serialises them; passing pydantic models
    would couple the queue payload to a schema version and break in-flight jobs on
    every deploy.
    """
    job_id = uuid.UUID(job_id_str)
    project_id = uuid.UUID(project_id_str)

    log.info(
        "diagnose.started",
        job_id=job_id_str,
        project_id=project_id_str,
        start_date=start_date,
        granularity=granularity,
        threshold_c=threshold_c,
        build_ladder=build_ladder,
    )

    with session_scope() as session:
        JobRepository(session).mark_running(job_id, stage=DIAGNOSE_STAGES[0][0])

    try:
        with session_scope() as session:
            outcome = run_diagnose_pipeline(
                session=session,
                settings=get_settings(),
                job_id=job_id,
                project_id=project_id,
                start_date=start_date,
                start_time=start_time,
                granularity=granularity,
                threshold_c=threshold_c,
                build_ladder_steps=build_ladder,
            )
    except FortyGuardError as exc:
        # The upstream detail goes to the log; the user gets something actionable.
        log.warning("diagnose.upstream_failed", job_id=job_id_str, detail=str(exc))
        _fail(
            job_id,
            "The temperature service could not complete this analysis. Cached and "
            "fixture data remain available.",
        )
    except PipelineError as exc:
        log.warning("diagnose.pipeline_error", job_id=job_id_str, detail=str(exc))
        _fail(job_id, str(exc))
    except Exception as exc:  # the job must reach a terminal state
        log.exception("diagnose.failed", job_id=job_id_str)
        _fail(job_id, f"{type(exc).__name__}: {exc}")
    else:
        # `degraded` means usable-but-partial, and it is distinct from success so
        # the UI shows the caveat rather than presenting a gap as complete.
        if outcome.degraded_reason is not None:
            _degrade(job_id, outcome.degraded_reason)
        else:
            _complete(job_id)

        log.info(
            "diagnose.finished",
            job_id=job_id_str,
            tiles=outcome.tile_count,
            ladders=outcome.ladder_tiles,
            attributed=outcome.attributed_tiles,
            degraded=outcome.degraded_reason is not None,
        )


def run_plan(
    job_id_str: str,
    project_id_str: str,
    budget_usd: float,
    objective: str,
    equity_lambda: float,
    threshold_c: float,
) -> None:
    """Execute the plan-generation pipeline."""
    job_id = uuid.UUID(job_id_str)

    log.info(
        "plan.started",
        job_id=job_id_str,
        project_id=project_id_str,
        budget_usd=budget_usd,
        objective=objective,
        equity_lambda=equity_lambda,
    )

    with session_scope() as session:
        JobRepository(session).mark_running(job_id, stage=PLAN_STAGES[0][0])

    try:
        with session_scope() as session:
            outcome = run_plan_pipeline(
                session=session,
                settings=get_settings(),
                job_id=job_id,
                project_id=uuid.UUID(project_id_str),
                budget_usd=budget_usd,
                objective=objective,
                equity_lambda=equity_lambda,
                threshold_c=threshold_c,
            )
    except PlanPipelineError as exc:
        # These messages name the missing piece — an empty catalog, no diagnosis,
        # nothing affordable — because "plan generation failed" is unactionable.
        log.warning("plan.precondition_failed", job_id=job_id_str, detail=str(exc))
        _fail(job_id, str(exc))
    except Exception as exc:
        log.exception("plan.failed", job_id=job_id_str)
        _fail(job_id, f"{type(exc).__name__}: {exc}")
    else:
        if outcome.degraded_reason is not None:
            _degrade(job_id, outcome.degraded_reason)
        else:
            _complete(job_id)

        log.info(
            "plan.finished",
            job_id=job_id_str,
            plan_id=str(outcome.plan_id),
            items=outcome.item_count,
            total_cost_usd=outcome.total_cost_usd,
            infeasible=outcome.infeasible_count,
        )
