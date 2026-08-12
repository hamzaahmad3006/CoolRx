"""RQ job entry points.

Each task owns a job's whole lifecycle: it marks the job running, advances it
through the declared stages, and always reaches a terminal state. The `finally`
discipline matters more than it looks — a task that raised without marking the job
failed would leave the frontend polling a job that will never change, which is
indistinguishable from slow progress.

Pipeline stages call into `geo`, `ml` and `optimizer`. Those modules are the subject
of Tasks 3–5 and are not implemented yet, so a run currently fails at the first
missing stage with a message naming it. That is deliberate: the alternative is
inventing temperature data to make the pipeline appear to work, which would put
fabricated numbers in front of the person evaluating the tool.
"""

from __future__ import annotations

import uuid

import structlog

from repositories.base import session_scope
from repositories.jobs import DIAGNOSE_STAGES, PLAN_STAGES, JobRepository

log = structlog.get_logger(__name__)


class StageNotImplementedError(RuntimeError):
    """A pipeline stage whose module has not been built yet.

    Distinct from a runtime failure so the job's error message can say what is
    missing rather than reporting a generic crash.
    """


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
        _advance(job_id, "validating", 5)

        # ── Stages below require the pipeline modules (Tasks 3-5) ─────────────
        raise StageNotImplementedError(
            "The temperature-fetch stage requires the geo module (Task 3) and a "
            "FortyGuard API key. No fixtures are committed yet, so there is no "
            "data to serve — see data/fixtures/README.md."
        )

    except StageNotImplementedError as exc:
        # Not marked degraded: degraded means partial-but-usable results, and there
        # are no results here at all.
        log.warning("diagnose.stage_missing", job_id=job_id_str, detail=str(exc))
        _fail(job_id, str(exc))
    except Exception as exc:  # noqa: BLE001 — the job must reach a terminal state
        log.exception("diagnose.failed", job_id=job_id_str)
        _fail(job_id, f"{type(exc).__name__}: {exc}")
    else:  # pragma: no cover — unreachable until the stages land
        _complete(job_id)


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
        _advance(job_id, "loading_catalog", 10)
        raise StageNotImplementedError(
            "Plan generation requires the optimizer (Task 5), the trained model "
            "(Task 4), and a populated intervention catalog."
        )
    except StageNotImplementedError as exc:
        log.warning("plan.stage_missing", job_id=job_id_str, detail=str(exc))
        _fail(job_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        log.exception("plan.failed", job_id=job_id_str)
        _fail(job_id, f"{type(exc).__name__}: {exc}")
    else:  # pragma: no cover
        _complete(job_id)
