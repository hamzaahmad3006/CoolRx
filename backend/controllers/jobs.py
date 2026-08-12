"""Job controller — status reads and the progress stream.

The SSE generator polls the database rather than subscribing to a message bus. That
is a deliberate trade for a hackathon-scale system: RQ workers write progress to
Postgres anyway, so polling needs no extra infrastructure and cannot lose an event
the way an at-most-once pub/sub delivery can. The cost is up to `POLL_INTERVAL_S`
of latency on each transition, which is invisible next to a multi-minute pipeline.

The stream always sends a terminal frame before closing. A client that saw the
connection drop without one would have no way to distinguish a finished job from a
dead server, and would sit on a spinner forever.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import structlog

from repositories.base import session_scope
from repositories.jobs import TERMINAL_STATUSES, JobRepository
from schemas.jobs import JobProgressEvent, JobResponse

from .adapters import job_to_response
from .errors import NotFoundError

log = structlog.get_logger(__name__)

#: Poll cadence for the SSE stream.
POLL_INTERVAL_S = 1.0

#: Hard ceiling on stream lifetime. Without it a browser tab left open on a
#: crashed job holds a connection and a database session indefinitely.
MAX_STREAM_SECONDS = 1_800

#: Comment frame keeping proxies from closing an idle connection. Sent as an SSE
#: comment so clients ignore it without needing a handler.
HEARTBEAT = ": keep-alive\n\n"

#: Emitted every N polls when nothing changed.
HEARTBEAT_EVERY = 15


class JobController:
    def __init__(self, session_factory: object | None = None) -> None:
        # The controller opens its own short-lived sessions per poll rather than
        # holding one for the stream's lifetime, which would pin a connection from
        # the pool for up to MAX_STREAM_SECONDS.
        self._unused = session_factory

    def get(self, job_id: uuid.UUID) -> JobResponse:
        with session_scope() as session:
            job = JobRepository(session).get(job_id)
            if job is None:
                raise NotFoundError(
                    message=f"No job with id {job_id}.", field="jobId"
                )
            return job_to_response(job)

    def list_for_project(self, project_id: uuid.UUID) -> list[JobResponse]:
        with session_scope() as session:
            rows = JobRepository(session).list_for_project(project_id)
            return [job_to_response(row) for row in rows]

    async def stream(self, job_id: uuid.UUID) -> AsyncIterator[str]:
        """Yield SSE frames until the job reaches a terminal state.

        The first frame is sent immediately so a client that connects after the job
        already finished still receives its result rather than waiting a poll
        interval for a job that will never change again.
        """
        elapsed = 0.0
        polls = 0
        last_signature: tuple[str, str | None, int] | None = None

        while elapsed < MAX_STREAM_SECONDS:
            snapshot = await asyncio.to_thread(self._snapshot, job_id)
            if snapshot is None:
                yield _frame(
                    "error",
                    f'{{"message":"No job with id {job_id}."}}',
                )
                return

            signature = (snapshot.status, snapshot.stage, snapshot.progress_pct)
            if signature != last_signature:
                event = JobProgressEvent(
                    job_id=snapshot.id,
                    stage=snapshot.stage or snapshot.status,
                    progress_pct=snapshot.progress_pct,
                    message=snapshot.error or snapshot.stage or snapshot.status,
                    elapsed_s=snapshot.elapsed_s,
                    status=snapshot.status,
                )
                yield _frame("progress", event.model_dump_json(by_alias=True))
                last_signature = signature
                polls = 0
            else:
                polls += 1
                if polls % HEARTBEAT_EVERY == 0:
                    yield HEARTBEAT

            if snapshot.status in TERMINAL_STATUSES:
                # An explicit terminal frame, so the client closes on a result
                # rather than on a dropped connection.
                yield _frame("done", snapshot.model_dump_json(by_alias=True))
                return

            await asyncio.sleep(POLL_INTERVAL_S)
            elapsed += POLL_INTERVAL_S

        log.warning("job.stream_timeout", job_id=str(job_id), elapsed_s=elapsed)
        yield _frame(
            "error",
            '{"message":"Progress stream timed out. Re-open it to resume '
            'watching; the job itself is unaffected."}',
        )

    @staticmethod
    def _snapshot(job_id: uuid.UUID) -> JobResponse | None:
        with session_scope() as session:
            job = JobRepository(session).get(job_id)
            return None if job is None else job_to_response(job)


def _frame(event: str, data: str) -> str:
    """One SSE frame. The blank line is the record separator and is required."""
    return f"event: {event}\ndata: {data}\n\n"
