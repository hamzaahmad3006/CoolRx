"""FortyGuard request cache and audit repository.

This repository backs three things at once from one table, which is why
`fg_requests` is never truncated:

  1. **Cache** — a repeated request is served from here and costs no credits.
  2. **Audit trail** — every request, successful or not, with its activity id.
  3. **Provenance** — the chain that lets any displayed figure be traced back to
     the FortyGuard task that produced it (SRS §20.2).

It also supplies the callbacks the client depends on (`cache_get`, `cache_put`,
`audit`, `submissions_today`), which is how the client stays free of database
coupling and unit-testable without a database.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .tables import FgRequest

if TYPE_CHECKING:
    # Type-only import. Importing the client at runtime would make every
    # repository depend on httpx and invert the layering — the client calls into
    # these callbacks, not the other way round.
    from clients.fortyguard.client import AuditRecord

log = structlog.get_logger(__name__)

#: Keys stripped from a request body before it is persisted. The API key is
#: passed as a header and never appears in a body, but stripping defensively
#: means a future change cannot quietly start storing a credential.
_SECRET_KEYS = frozenset({"api-key", "api_key", "authorization", "token"})


def _strip_secrets(body: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k.lower() not in _SECRET_KEYS}


class FgCacheRepository:
    """Persistence for FortyGuard requests, responses and audit records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Cache ────────────────────────────────────────────────────────────────

    def get_result(self, request_hash: str) -> dict[str, Any] | None:
        """Return a previously completed result, or None.

        Only `Completed` rows are cache hits — a failed or in-flight request must
        not satisfy a later call.
        """
        stmt = select(FgRequest.response).where(
            FgRequest.request_hash == request_hash,
            FgRequest.status == "Completed",
            FgRequest.response.is_not(None),
        )
        row = self._session.execute(stmt).first()
        if row is None:
            return None
        response = row[0]
        return response if isinstance(response, dict) else None

    def put_result(
        self,
        request_hash: str,
        endpoint: str,
        request_body: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        """Store a completed result.

        Upserts on `request_hash`. The unique constraint makes a duplicate
        impossible, so a concurrent worker that raced to the same request cannot
        create a second row — it updates the existing one instead.
        """
        stmt = (
            pg_insert(FgRequest)
            .values(
                endpoint=endpoint,
                request_hash=request_hash,
                request_body=_strip_secrets(request_body),
                status="Completed",
                http_status=200,
                completed_at=datetime.now(UTC),
                response=result,
                credits_charged=True,
            )
            .on_conflict_do_update(
                index_elements=[FgRequest.request_hash],
                set_={
                    "status": "Completed",
                    "response": result,
                    "completed_at": datetime.now(UTC),
                },
            )
        )
        self._session.execute(stmt)

    # ── Audit ────────────────────────────────────────────────────────────────

    def record(self, audit: AuditRecord) -> None:
        """Persist an audit record for any outcome, including failures.

        Failures are recorded deliberately: the `activity_id` is what FortyGuard
        support would need to investigate a task that failed upstream, and
        discarding it because the call did not succeed would throw away the only
        handle on it.
        """
        stmt = (
            pg_insert(FgRequest)
            .values(
                endpoint=audit.endpoint,
                request_hash=audit.request_hash,
                request_body=_strip_secrets(audit.request_body),
                activity_id=audit.activity_id,
                status=audit.status,
                http_status=audit.http_status,
                poll_count=audit.poll_count,
                latency_ms=audit.latency_ms,
                credits_charged=audit.credits_charged,
                from_fixture=audit.from_fixture,
                error=audit.error,
                completed_at=(
                    datetime.now(UTC) if audit.status == "Completed" else None
                ),
            )
            .on_conflict_do_update(
                index_elements=[FgRequest.request_hash],
                set_={
                    "activity_id": audit.activity_id,
                    "status": audit.status,
                    "http_status": audit.http_status,
                    "poll_count": audit.poll_count,
                    "latency_ms": audit.latency_ms,
                    "credits_charged": audit.credits_charged,
                    "error": audit.error,
                },
            )
        )
        self._session.execute(stmt)

    # ── Credit accounting ────────────────────────────────────────────────────

    def submissions_today(self) -> int:
        """Count of chargeable completions in the last 24 hours.

        This is the local fallback for credit accounting. FortyGuard's
        credits-usage endpoint is listed in their docs sidebar but its path and
        response schema are not documented in prose (SRS C-10), so the guard must
        work without it. Counting our own successful submissions is a lower bound
        we always have.
        """
        since = datetime.now(UTC) - timedelta(days=1)
        stmt = select(func.count()).where(
            FgRequest.credits_charged.is_(True),
            FgRequest.submitted_at >= since,
        )
        return int(self._session.execute(stmt).scalar_one())

    def provenance_for(self, request_hash: str) -> FgRequest | None:
        stmt = select(FgRequest).where(FgRequest.request_hash == request_hash)
        return self._session.execute(stmt).scalar_one_or_none()

    def total_charged(self) -> int:
        stmt = select(func.count()).where(FgRequest.credits_charged.is_(True))
        return int(self._session.execute(stmt).scalar_one())


def make_client_hooks(
    session: Session,
) -> tuple[
    Callable[[str], dict[str, Any] | None],
    Callable[[str, str, dict[str, Any], dict[str, Any]], None],
    Callable[[AuditRecord], None],
    Callable[[], int],
]:
    """Build the callbacks `FortyGuardClient` expects.

    Returned as plain functions so the client never imports a repository and can
    be tested with in-memory stand-ins.
    """
    repo = FgCacheRepository(session)
    return (repo.get_result, repo.put_result, repo.record, repo.submissions_today)
