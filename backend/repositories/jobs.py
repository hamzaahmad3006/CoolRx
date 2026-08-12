"""Job lifecycle persistence.

Jobs are what the frontend polls, so this module's job is to make progress
honest. Two rules are enforced here rather than left to callers:

  * **Progress never goes backwards.** A stage that recomputes and reports a
    lower percentage would look to the user like the pipeline restarted.
  * **A terminal status is final.** A late worker heartbeat cannot move a failed
    job back to running, which would hide a failure the user already saw.

`degraded` is a first-class outcome, not a variant of failure: a run that
completed with a partial FortyGuard response is usable and must say so (SRS §19).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Final, Literal

import structlog
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .tables import Job

log = structlog.get_logger(__name__)

JobKind = Literal["diagnose", "plan", "verify", "harvest"]
JobStatus = Literal["queued", "running", "completed", "failed", "degraded"]

#: Statuses after which no further transition is accepted.
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset(
    {"completed", "failed", "degraded"}
)

#: Ordered pipeline stages with the progress each implies, so the API and the
#: worker cannot disagree about what "enriching" means numerically.
DIAGNOSE_STAGES: Final[tuple[tuple[str, int], ...]] = (
    ("validating", 5),
    ("fetching_temperature", 25),
    ("building_ladder", 45),
    ("enriching_features", 60),
    ("computing_exposure", 75),
    ("attributing", 90),
    ("finalizing", 100),
)

PLAN_STAGES: Final[tuple[tuple[str, int], ...]] = (
    ("loading_catalog", 10),
    ("scoring_candidates", 40),
    ("optimizing", 70),
    ("writing_rationales", 90),
    ("finalizing", 100),
)


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, kind: JobKind, project_id: uuid.UUID | None = None) -> Job:
        job = Job(project_id=project_id, kind=kind, status="queued", progress_pct=0)
        self._session.add(job)
        self._session.flush()
        log.info("job.created", job_id=str(job.id), kind=kind)
        return job

    def get(self, job_id: uuid.UUID) -> Job | None:
        return self._session.get(Job, job_id)

    def mark_running(self, job_id: uuid.UUID, stage: str | None = None) -> bool:
        return self._transition(job_id, status="running", stage=stage)

    def advance(self, job_id: uuid.UUID, *, stage: str, progress_pct: int) -> bool:
        """Move a job forward. A lower percentage than the current one is ignored."""
        job = self.get(job_id)
        if job is None:
            return False
        if job.status in TERMINAL_STATUSES:
            log.warning(
                "job.advance_after_terminal",
                job_id=str(job_id),
                status=job.status,
                attempted_stage=stage,
            )
            return False

        clamped = max(0, min(100, progress_pct))
        if clamped < job.progress_pct:
            log.warning(
                "job.progress_regression_ignored",
                job_id=str(job_id),
                current=job.progress_pct,
                attempted=clamped,
                stage=stage,
            )
            clamped = job.progress_pct

        job.status = "running"
        job.stage = stage
        job.progress_pct = clamped
        job.updated_at = datetime.now(UTC)
        return True

    def complete(self, job_id: uuid.UUID) -> bool:
        return self._transition(
            job_id, status="completed", stage="finalizing", progress_pct=100
        )

    def degrade(self, job_id: uuid.UUID, reason: str) -> bool:
        """Finish with usable but incomplete results.

        The reason is stored and surfaced; a degraded run that looks identical to
        a clean one would misrepresent its own coverage.
        """
        return self._transition(
            job_id, status="degraded", progress_pct=100, error=reason
        )

    def fail(self, job_id: uuid.UUID, error: str) -> bool:
        return self._transition(job_id, status="failed", error=error)

    def _transition(
        self,
        job_id: uuid.UUID,
        *,
        status: JobStatus,
        stage: str | None = None,
        progress_pct: int | None = None,
        error: str | None = None,
    ) -> bool:
        job = self.get(job_id)
        if job is None:
            return False
        if job.status in TERMINAL_STATUSES:
            log.warning(
                "job.transition_after_terminal",
                job_id=str(job_id),
                current=job.status,
                attempted=status,
            )
            return False

        job.status = status
        if stage is not None:
            job.stage = stage
        if progress_pct is not None:
            job.progress_pct = max(job.progress_pct, max(0, min(100, progress_pct)))
        if error is not None:
            job.error = error
        job.updated_at = datetime.now(UTC)

        log.info(
            "job.transition",
            job_id=str(job_id),
            status=status,
            stage=job.stage,
            progress_pct=job.progress_pct,
        )
        return True

    def find_active(self, *, project_id: uuid.UUID, kind: JobKind) -> Job | None:
        """An in-flight job of this kind for this project, if one exists.

        Used to refuse a duplicate rather than queue it: two concurrent diagnose
        runs on one project would both spend credits computing the same thing.
        """
        stmt = (
            select(Job)
            .where(
                Job.project_id == project_id,
                Job.kind == kind,
                Job.status.in_(["queued", "running"]),
            )
            .order_by(Job.created_at.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_for_project(self, project_id: uuid.UUID, limit: int = 20) -> list[Job]:
        stmt = (
            select(Job)
            .where(Job.project_id == project_id)
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
        return list(self._session.execute(stmt).scalars())

    def reap_stale(self, *, older_than: datetime) -> int:
        """Fail jobs whose worker died without reporting.

        Without this, a killed worker leaves a job polling at 40% forever. The
        frontend cannot distinguish that from slow progress, so the reaper turns
        it into an explicit failure.
        """
        stmt = (
            update(Job)
            .where(
                Job.status.in_(["queued", "running"]),
                Job.updated_at < older_than,
            )
            .values(
                status="failed",
                error="Worker stopped reporting; job was reaped as stale.",
                updated_at=datetime.now(UTC),
            )
        )
        result = self._session.execute(stmt)
        count = int(result.rowcount or 0)
        if count:
            log.warning("job.reaped_stale", count=count)
        return count
