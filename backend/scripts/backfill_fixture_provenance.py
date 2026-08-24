"""Add provenance to fixtures captured before the envelope carried any.

    python -m scripts.backfill_fixture_provenance --dry-run
    python -m scripts.backfill_fixture_provenance

The first 28 recordings were written as a bare `{map_data, stats_data}` result,
because the harvest wrote `result.result` straight to disk instead of going
through `FixtureStore.save`. That left them with no district, no request body and
no `activity_id` — so both harvested districts read back as "unknown", a grouped
holdout was impossible however many were captured, and FR-019 had no activity_id
to resolve a fixture-backed figure against.

Re-harvesting would fix it and cost 28 live calls. It is not necessary: the
filename *is* `compute_request_hash(endpoint, payload)`, and the payload is
regenerated deterministically from the district presets. So replaying every
district's plan reconstructs the hash → (district, payload) mapping exactly, and
the missing metadata can be restored offline.

What cannot be recovered is `activity_id`: it was returned by the live API and
never written down. It is set to null rather than invented, and the absence is
recorded as `provenance_backfilled: true` so a reviewer can see which recordings
have a real task id behind them and which do not.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from clients.fortyguard.cache import compute_request_hash
from core.config import get_settings
from scripts.harvest_fixtures import DISTRICTS, _payload, _plan


def _expected() -> dict[str, dict[str, Any]]:
    """hash → provenance, for every call in every district's plan."""
    settings = get_settings()
    table: dict[str, dict[str, Any]] = {}

    for key, district in DISTRICTS.items():
        calls = _plan(
            district, settings.fg_default_granularity, settings.fg_ladder_steps
        )
        for analytic, threshold in calls:
            payload = _payload(
                district,
                analytic=analytic,
                granularity=settings.fg_default_granularity,
                threshold=threshold,
            )
            digest = compute_request_hash("heatmap", payload)
            table[digest] = {
                "request_hash": digest,
                "endpoint": "heatmap",
                "request_body": payload,
                "district": key,
                "district_name": district.name,
                "analytic_type": analytic,
                "threshold_c": threshold,
                # Never observed for these recordings; not invented.
                "activity_id": None,
                "provenance_backfilled": True,
                "backfilled_at": datetime.now(UTC).isoformat(),
            }
    return table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    settings = get_settings()
    fixture_dir = Path(settings.fixture_dir)
    table = _expected()

    upgraded = already = unknown = 0
    for path in sorted(fixture_dir.glob("*.json")):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print(f"  [ unreadable] {path.name}")
            continue

        if isinstance(body, dict) and "request_hash" in body:
            already += 1
            continue

        meta = table.get(path.stem)
        if meta is None:
            # A recording whose request cannot be reproduced from any preset.
            # Left exactly as it is: guessing which district it came from would
            # put a wrong label on real data.
            print(f"  [  unmatched] {path.name}")
            unknown += 1
            continue

        payload = {**meta, "response": body}
        if not args.dry_run:
            path.write_text(
                json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
                encoding="utf-8",
            )
        upgraded += 1
        label = f"{meta['district']}/{meta['analytic_type']}"
        thr = meta["threshold_c"]
        print(
            f"  [{'would fix' if args.dry_run else '     fixed'}] {label}"
            f"{f' @ {thr}' if thr is not None else ''}"
        )

    print(
        f"\n  {upgraded} upgraded, {already} already had provenance, "
        f"{unknown} unmatched"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
