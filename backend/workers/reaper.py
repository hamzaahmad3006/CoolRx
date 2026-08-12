"""Stale-job reaper.

    python -m workers.reaper            # one pass
    python -m workers.reaper --loop     # run continuously

A killed worker leaves its job sitting at whatever progress it last reported. The
frontend cannot distinguish that from slow work and shows a spinner indefinitely, so
the reaper converts silence into an explicit failure the UI can render.

The threshold is generous on purpose: a legitimate FortyGuard poll can take minutes
(SRS §11 puts the deadline at 600 s), so a stall is only called after well past that.
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime, timedelta

import structlog

from repositories.base import session_scope
from repositories.jobs import JobRepository

log = structlog.get_logger(__name__)

#: How long a job may go without a progress update before it is reaped. Longer than
#: the FortyGuard poll deadline so a slow-but-alive task is never killed.
STALE_AFTER = timedelta(minutes=20)

SWEEP_INTERVAL_SECONDS = 120


def sweep() -> int:
    cutoff = datetime.now(UTC) - STALE_AFTER
    with session_scope() as session:
        return JobRepository(session).reap_stale(older_than=cutoff)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true", help="Sweep continuously")
    parser.add_argument(
        "--interval",
        type=int,
        default=SWEEP_INTERVAL_SECONDS,
        help="Seconds between sweeps in loop mode",
    )
    args = parser.parse_args(argv)

    if not args.loop:
        count = sweep()
        print(f"reaped {count} stale job(s)")
        return 0

    log.info("reaper.started", interval_s=args.interval)
    while True:
        try:
            sweep()
        except Exception:  # noqa: BLE001 — a sweep failure must not kill the loop
            log.exception("reaper.sweep_failed")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
