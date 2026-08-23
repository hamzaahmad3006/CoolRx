"""Enqueue helpers — the boundary between a request and the job system.

Kept separate from `queue.py` so controllers depend on these narrow functions rather
than on RQ itself, and can be handed a fake in tests.

Both functions raise `EnqueueFailed` rather than swallowing a Redis outage. The
caller must know, because a job row with nothing to run it is worse than an
immediate error: the client would poll a job that can never change.
"""

from __future__ import annotations

import uuid

import structlog

log = structlog.get_logger(__name__)


class EnqueueFailed(RuntimeError):
    """The job could not be handed to a worker."""


def enqueue_diagnose(
    *,
    job_id: uuid.UUID,
    project_id: uuid.UUID,
    start_date: str,
    start_time: str,
    granularity: int,
    threshold_c: float,
    build_ladder: bool,
) -> str:
    from .queue import get_queue
    from .tasks import run_diagnose

    try:
        enqueued = get_queue().enqueue(
            run_diagnose,
            str(job_id),
            str(project_id),
            start_date,
            start_time,
            granularity,
            threshold_c,
            build_ladder,
            # Dash, not colon: RQ 2.x rejects a colon in a job id, and the
            # rejection message ("must only contain letters, numbers,
            # underscores and dashes") does not name the offending character.
            # A UUID satisfies that rule; the separator did not.
            job_id=f"diagnose-{job_id}",
        )
    except Exception as exc:  # noqa: BLE001 — surfaced as EnqueueFailed
        log.error("enqueue.failed", kind="diagnose", detail=str(exc))
        raise EnqueueFailed(str(exc)) from exc

    log.info("enqueue.ok", kind="diagnose", job_id=str(job_id))
    return str(enqueued.id)


def enqueue_plan(
    *,
    job_id: uuid.UUID,
    project_id: uuid.UUID,
    budget_usd: float,
    objective: str,
    equity_lambda: float,
    threshold_c: float,
) -> str:
    from .queue import get_queue
    from .tasks import run_plan

    try:
        enqueued = get_queue().enqueue(
            run_plan,
            str(job_id),
            str(project_id),
            budget_usd,
            objective,
            equity_lambda,
            threshold_c,
            job_id=f"plan-{job_id}",
        )
    except Exception as exc:  # noqa: BLE001
        log.error("enqueue.failed", kind="plan", detail=str(exc))
        raise EnqueueFailed(str(exc)) from exc

    log.info("enqueue.ok", kind="plan", job_id=str(job_id))
    return str(enqueued.id)
