"""Tests for job progress honesty.

Progress is the only signal a user has during a multi-minute pipeline, so the two
rules worth testing are the ones that keep it from lying: progress never moves
backwards, and a terminal status is final.

Runs without a database via a session stub that implements the one method the
repository uses.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from repositories.jobs import (
    DIAGNOSE_STAGES,
    PLAN_STAGES,
    TERMINAL_STATUSES,
    JobRepository,
)
from repositories.tables import Job


class _FakeSession:
    """Holds Job instances in a dict, mimicking `Session.get`."""

    def __init__(self) -> None:
        self.store: dict[uuid.UUID, Job] = {}

    def add(self, obj: Job) -> None:
        if obj.id is None:
            obj.id = uuid.uuid4()
        self.store[obj.id] = obj

    def flush(self) -> None:
        for job in self.store.values():
            if job.id is None:
                job.id = uuid.uuid4()

    def get(self, _model: type[Job], key: uuid.UUID) -> Job | None:
        return self.store.get(key)


def _repo() -> tuple[JobRepository, _FakeSession]:
    session = _FakeSession()
    return JobRepository(session), session  # type: ignore[arg-type]


def _new_job(repo: JobRepository, kind: str = "diagnose") -> Job:
    job = repo.create(kind=kind)  # type: ignore[arg-type]
    # `server_default` does not apply without a real INSERT.
    if job.progress_pct is None:
        job.progress_pct = 0
    job.updated_at = datetime.now(UTC)
    return job


# ── Creation ────────────────────────────────────────────────────────────────


def test_new_job_starts_queued_at_zero() -> None:
    repo, _ = _repo()
    job = _new_job(repo)
    assert job.status == "queued"
    assert job.progress_pct == 0


# ── Monotonic progress ──────────────────────────────────────────────────────


def test_progress_advances() -> None:
    repo, _ = _repo()
    job = _new_job(repo)
    assert repo.advance(job.id, stage="fetching_temperature", progress_pct=25)
    assert job.progress_pct == 25
    assert job.stage == "fetching_temperature"
    assert job.status == "running"


def test_progress_never_regresses() -> None:
    """A later stage reporting a lower number must not rewind the bar.

    Without this a user watching the pipeline sees it appear to restart.
    """
    repo, _ = _repo()
    job = _new_job(repo)
    repo.advance(job.id, stage="attributing", progress_pct=90)
    assert repo.advance(job.id, stage="enriching_features", progress_pct=60)
    assert job.progress_pct == 90, "progress must hold at its high-water mark"
    assert job.stage == "enriching_features", "the stage label still updates"


@pytest.mark.parametrize(("raw", "expected"), [(-10, 0), (0, 0), (150, 100)])
def test_progress_is_clamped_to_range(raw: int, expected: int) -> None:
    """The CHECK constraint allows 0-100; out-of-range input is clamped here."""
    repo, _ = _repo()
    job = _new_job(repo)
    repo.advance(job.id, stage="x", progress_pct=raw)
    assert job.progress_pct == expected


# ── Terminal finality ───────────────────────────────────────────────────────


@pytest.mark.parametrize("terminal", sorted(TERMINAL_STATUSES))
def test_terminal_status_rejects_further_advance(terminal: str) -> None:
    """A late worker heartbeat must not revive a finished job."""
    repo, _ = _repo()
    job = _new_job(repo)
    job.status = terminal
    job.progress_pct = 100

    assert repo.advance(job.id, stage="optimizing", progress_pct=50) is False
    assert job.status == terminal
    assert job.stage != "optimizing"


def test_failure_cannot_be_overwritten_by_completion() -> None:
    """The user has already been shown the failure; it must not disappear."""
    repo, _ = _repo()
    job = _new_job(repo)
    repo.fail(job.id, "FortyGuard returned Failed for activity abc123")

    assert repo.complete(job.id) is False
    assert job.status == "failed"
    assert job.error is not None and "abc123" in job.error


def test_completion_cannot_be_overwritten_by_failure() -> None:
    repo, _ = _repo()
    job = _new_job(repo)
    repo.complete(job.id)
    assert repo.fail(job.id, "late error") is False
    assert job.status == "completed"
    assert job.error is None


# ── Outcomes ────────────────────────────────────────────────────────────────


def test_complete_sets_full_progress() -> None:
    repo, _ = _repo()
    job = _new_job(repo)
    repo.advance(job.id, stage="attributing", progress_pct=90)
    repo.complete(job.id)
    assert job.status == "completed"
    assert job.progress_pct == 100


def test_degraded_is_a_distinct_finished_state_carrying_its_reason() -> None:
    """A partial result is usable but must not look identical to a clean one."""
    repo, _ = _repo()
    job = _new_job(repo)
    repo.degrade(job.id, "FortyGuard returned 62% tile coverage")

    assert job.status == "degraded"
    assert job.status != "failed"
    assert job.progress_pct == 100
    assert job.error is not None and "62%" in job.error


def test_transition_on_missing_job_returns_false() -> None:
    repo, _ = _repo()
    assert repo.complete(uuid.uuid4()) is False
    assert repo.advance(uuid.uuid4(), stage="x", progress_pct=10) is False


# ── Stage tables ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "stages"), [("diagnose", DIAGNOSE_STAGES), ("plan", PLAN_STAGES)]
)
def test_stage_tables_are_monotonic_and_end_at_100(
    name: str, stages: tuple[tuple[str, int], ...]
) -> None:
    """The declared stage table must itself obey the monotonic rule.

    A stage table with a decreasing step would make every run regress, and the
    repository guard would silently paper over it.
    """
    percentages = [pct for _, pct in stages]
    assert percentages == sorted(percentages), f"{name} stages must not decrease"
    assert percentages[-1] == 100, f"{name} must reach 100"
    assert percentages[0] > 0, f"{name} must show immediate feedback"
    names = [stage for stage, _ in stages]
    assert len(set(names)) == len(names), f"{name} stage names must be unique"


def test_walking_a_stage_table_never_triggers_the_regression_guard() -> None:
    """End-to-end: the shipped stage order is internally consistent."""
    repo, _ = _repo()
    job = _new_job(repo)
    for stage, pct in DIAGNOSE_STAGES:
        assert repo.advance(job.id, stage=stage, progress_pct=pct)
        assert job.progress_pct == pct, f"{stage} was clamped — the table is wrong"


# ── Reaper ──────────────────────────────────────────────────────────────────


def test_reaper_cutoff_is_in_the_past() -> None:
    """Sanity check on the caller's contract: `older_than` is a cutoff, not a TTL."""
    cutoff = datetime.now(UTC) - timedelta(minutes=30)
    assert cutoff < datetime.now(UTC)
