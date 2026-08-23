"""Persistence for agent runs.

The `agent_runs` table has existed since the initial schema and nothing ever wrote
to it. `plan_pipeline` ran the narrator, took its rationales and discarded the
rest — the node timings, the guard verdict, the violations — so `/agent/runs/{id}/trace`
had nothing to serve and the Agent Trace page had no source but a fixture.

Storing the run is not bookkeeping. CoolRx's central claim is that the language
model never originates an authoritative number, and the guard verdict is the
evidence for it. A claim whose evidence is thrown away after each run is an
assertion.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from .tables import AgentRun

log = structlog.get_logger(__name__)


class AgentRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        run_id: uuid.UUID,
        plan_id: uuid.UUID,
        graph_version: str,
        model: str,
        nodes: list[dict[str, Any]],
        guard_verdict: str,
        guard_violations: list[dict[str, Any]],
        tokens_in: int | None,
        tokens_out: int | None,
        duration_ms: int | None,
    ) -> AgentRun:
        """Store one narration run, verdict and all.

        A failed guard verdict is recorded exactly like a clean one. Persisting
        only the runs that passed would make the trace a highlight reel.
        """
        run = AgentRun(
            id=run_id,
            plan_id=plan_id,
            graph_version=graph_version,
            model=model,
            nodes=nodes,
            guard_verdict=guard_verdict,
            guard_violations=guard_violations,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_ms=duration_ms,
        )
        self._session.add(run)
        self._session.flush()
        log.info(
            "agent_run.recorded",
            run_id=str(run_id),
            plan_id=str(plan_id),
            verdict=guard_verdict,
            violations=len(guard_violations),
        )
        return run

    def get(self, run_id: uuid.UUID) -> AgentRun | None:
        return self._session.get(AgentRun, run_id)

    def latest_for_plan(self, plan_id: uuid.UUID) -> AgentRun | None:
        """The most recent run for a plan.

        The trace page is reached from a plan, and a plan may be re-narrated, so
        the newest run is the one that produced the prose currently on screen.
        """
        stmt = (
            select(AgentRun)
            .where(AgentRun.plan_id == plan_id)
            .order_by(AgentRun.created_at.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()
