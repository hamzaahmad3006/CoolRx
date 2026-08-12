"""RQ queue and worker setup.

Synchronous by design. RQ workers fork and run sync code, and the FortyGuard client
is sync for the same reason, so there is one execution model across the whole
pipeline rather than a sync/async boundary to get wrong.
"""

from __future__ import annotations

from functools import lru_cache

import structlog
from redis import Redis
from rq import Queue

from core.config import get_settings

log = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url)


@lru_cache(maxsize=1)
def get_queue() -> Queue:
    settings = get_settings()
    return Queue(
        settings.rq_queue_name,
        connection=get_redis(),
        # A job that outlives its deadline is killed rather than left running: a
        # stuck pipeline holding a worker would block every later request, and the
        # reaper would mark it failed anyway.
        default_timeout=settings.job_deadline_seconds,
    )


def redis_available() -> bool:
    """Whether Redis answers. Used by the readiness probe."""
    try:
        return bool(get_redis().ping())
    except Exception:  # noqa: BLE001 — readiness must never raise
        return False
