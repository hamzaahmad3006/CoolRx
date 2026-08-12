"""Job status and progress-stream routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from controllers.jobs import JobController
from schemas.jobs import JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse, summary="Job status")
def get_job(job_id: uuid.UUID) -> JobResponse:
    return JobController().get(job_id)


@router.get(
    "/{job_id}/stream",
    summary="Server-sent progress stream",
    response_class=StreamingResponse,
)
async def stream_job(job_id: uuid.UUID) -> StreamingResponse:
    """SSE stream of progress frames until the job reaches a terminal state.

    `X-Accel-Buffering: no` disables nginx response buffering. Without it a proxy
    holds frames until its buffer fills, so progress arrives in one burst at the
    end — which looks exactly like a hung job for the whole run.
    """
    controller = JobController()
    return StreamingResponse(
        controller.stream(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
