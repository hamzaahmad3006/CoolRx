"""The agent trace.

Serves what the narrator actually did for a plan: each node, the numeric guard's
verdict, and any violations it caught.

This is the endpoint a sceptical judge should be pointed at. CoolRx's central
claim is that the language model never originates an authoritative number, and
this is where that claim becomes checkable rather than asserted — including when
the answer is that the guard rejected the model's text and it was discarded.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from repositories.agent import AgentRunRepository
from schemas.agent import AgentRunResponse

from .deps import SessionDep

router = APIRouter(prefix="/agent", tags=["agent"])


def _to_response(run) -> AgentRunResponse:
    return AgentRunResponse(
        id=run.id,
        plan_id=run.plan_id,
        graph_version=run.graph_version,
        model=run.model,
        nodes=run.nodes or [],
        guard_verdict=run.guard_verdict,
        guard_violations=run.guard_violations or [],
        tokens_in=run.tokens_in,
        tokens_out=run.tokens_out,
        duration_ms=run.duration_ms,
        created_at=run.created_at,
    )


@router.get(
    "/runs/{run_id}/trace",
    response_model=AgentRunResponse,
    summary="One narration run, with the guard verdict",
)
def agent_trace(run_id: uuid.UUID, session: SessionDep) -> AgentRunResponse:
    run = AgentRunRepository(session).get(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No agent run {run_id}",
        )
    return _to_response(run)


@router.get(
    "/plans/{plan_id}/trace",
    response_model=AgentRunResponse,
    summary="The latest narration run for a plan",
)
def latest_trace_for_plan(
    plan_id: uuid.UUID, session: SessionDep
) -> AgentRunResponse:
    """Reached from a plan, which is how the UI gets here.

    A plan can be re-narrated, so the newest run is the one that produced the
    prose currently on screen.
    """
    run = AgentRunRepository(session).latest_for_plan(plan_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No narration has been recorded for plan {plan_id}. A plan built "
                f"with no LLM provider configured has no trace, and the figures "
                f"are unaffected by that."
            ),
        )
    return _to_response(run)
