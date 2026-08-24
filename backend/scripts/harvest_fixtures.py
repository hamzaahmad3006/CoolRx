"""Capture FortyGuard responses as committed fixtures.

    python -m scripts.harvest_fixtures --list
    python -m scripts.harvest_fixtures --district phoenix --dry-run
    python -m scripts.harvest_fixtures --district phoenix

Run once, with a real API key. Every later run of the whole product — the demo, the
test suite, a judge cloning the repo — reads the captured files and spends nothing.

Fixtures are **recordings**, never hand-written. A fabricated temperature field
would launder invented measurements into every figure downstream, which is the same
violation as inventing a unit cost. That is why this script exists instead of a
seed file.

Cost: 14 calls per district — one `tcm`, one `time_of_measure`, one `persistence`,
and eleven `exceedance` rungs for the ladder. `--dry-run` prints the plan and the
exact cost without spending anything.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

from clients.fortyguard.cache import FixtureStore, compute_request_hash
from clients.fortyguard.client import FortyGuardClient
from clients.fortyguard.errors import FortyGuardError
from core.config import get_settings

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class District:
    """A preset district and the window to capture it in.

    A hot summer afternoon, because that is the case the product is about; a mild
    morning would produce fixtures where nothing exceeds any threshold and the
    ladder is uniformly zero.
    """

    key: str
    name: str
    west: float
    south: float
    east: float
    north: float
    start_date: str
    start_time: str
    threshold_c: float


DISTRICTS: dict[str, District] = {
    "phoenix": District(
        key="phoenix",
        name="Central Phoenix, AZ",
        west=-112.10, south=33.43, east=-112.07, north=33.455,
        start_date="2025-07-15",
        start_time="22:00",  # ~15:00 local — the afternoon peak
        threshold_c=35.0,
    ),
    "lasvegas": District(
        key="lasvegas",
        name="Downtown Las Vegas, NV",
        west=-115.16, south=36.16, east=-115.13, north=36.185,
        start_date="2025-07-16",
        start_time="22:00",
        threshold_c=35.0,
    ),
    "tucson": District(
        key="tucson",
        name="Central Tucson, AZ",
        west=-110.98, south=32.21, east=-110.95, north=32.235,
        start_date="2025-07-17",
        start_time="22:00",
        threshold_c=35.0,
    ),

    "phoenix_city": District(
        key="phoenix_city",
        name="Central Phoenix, AZ — city scale",
        west=-112.1431, south=33.394, east=-112.0269, north=33.491,
        start_date="2025-07-15",
        start_time="22:00",
        threshold_c=35.0,
    ),
    "lasvegas_city": District(
        key="lasvegas_city",
        name="Las Vegas, NV — city scale",
        west=-115.205, south=36.124, east=-115.085, north=36.221,
        start_date="2025-07-16",
        start_time="22:00",
        threshold_c=35.0,
    ),
    "tucson_city": District(
        key="tucson_city",
        name="Tucson, AZ — city scale",
        west=-111.0223, south=32.174, east=-110.9077, north=32.271,
        start_date="2025-07-17",
        start_time="22:00",
        threshold_c=35.0,
    ),
}


def _payload(
    district: District, *, analytic: str, granularity: int, threshold: float | None
) -> dict[str, object]:
    payload: dict[str, object] = {
        "polygon_aoi": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [district.west, district.south],
                                [district.east, district.south],
                                [district.east, district.north],
                                [district.west, district.north],
                                [district.west, district.south],
                            ]
                        ],
                    },
                }
            ],
        },
        "date_time": {
            "start_date": district.start_date,
            "start_time": district.start_time,
            "filter_type": 1,
        },
        "granularity": granularity,
        "analytic_type": analytic,
    }
    if threshold is not None:
        payload["threshold"] = threshold
        payload["direction"] = "above"
    return payload


def _plan(
    district: District, granularity: int, ladder_steps: int, *, tcm_only: bool = False
) -> list[tuple[str, float | None]]:
    """Every call a district needs, in order.

    `tcm_only` captures the temperature field alone, for training. The city-scale
    AOIs exist to give the model land-cover contrast to learn from, and the eleven
    exceedance rungs are a demo concern the small district fixtures already cover
    -- capturing the full ladder over 45 sq mi would spend fourteen calls and tens
    of megabytes per district to answer a question nothing asks at that scale.
    """
    if tcm_only:
        return [("tcm", None)]

    calls: list[tuple[str, float | None]] = [
        ("tcm", None),
        ("time_of_measure", None),
        ("persistence", district.threshold_c),
    ]
    calls.extend(
        ("exceedance", district.threshold_c + step)
        for step in range(ladder_steps + 1)
    )
    return calls


def harvest(
    district: District, *, dry_run: bool, tcm_only: bool = False,
    granularity: int | None = None,
) -> int:
    settings = get_settings()
    fixture_dir = Path(settings.fixture_dir)
    fixture_dir.mkdir(parents=True, exist_ok=True)

    granularity = granularity or settings.fg_default_granularity
    calls = _plan(
        district, granularity, settings.fg_ladder_steps, tcm_only=tcm_only
    )

    print(f"\n{district.name}  ({district.key})")
    print(f"  window     {district.start_date} {district.start_time} UTC")
    print(f"  threshold  {district.threshold_c} °C")
    print(f"  granularity {granularity} m")
    print(f"  calls      {len(calls)}")

    captured = 0
    skipped = 0

    if dry_run:
        for analytic, threshold in calls:
            payload = _payload(
                district,
                analytic=analytic,
                granularity=granularity,
                threshold=threshold,
            )
            digest = compute_request_hash("heatmap", payload)
            exists = (fixture_dir / f"{digest}.json").exists()
            label = "have" if exists else "WOULD FETCH"
            suffix = f" @ {threshold} °C" if threshold is not None else ""
            print(f"    [{label:>11}] {analytic}{suffix}  {digest[:12]}…")
            if exists:
                skipped += 1
        print(f"\n  {len(calls) - skipped} call(s) would be spent.")
        return 0

    if settings.fortyguard_api_key is None:
        print(
            "\nerror: FORTYGUARD_API_KEY is not set. Capturing fixtures needs a "
            "real key — that is the whole point of the exercise.",
            file=sys.stderr,
        )
        return 2

    # fixture_mode must be off, or the client would read the very files this
    # script is meant to create and capture nothing.
    if settings.fixture_mode:
        print(
            "\nerror: FIXTURE_MODE is on, so the client would serve fixtures rather "
            "than call the API. Re-run with FIXTURE_MODE=false.",
            file=sys.stderr,
        )
        return 2

    client = FortyGuardClient(settings)
    try:
        for analytic, threshold in calls:
            payload = _payload(
                district,
                analytic=analytic,
                granularity=granularity,
                threshold=threshold,
            )
            digest = compute_request_hash("heatmap", payload)
            target = fixture_dir / f"{digest}.json"
            suffix = f" @ {threshold} °C" if threshold is not None else ""

            if target.exists():
                print(f"    [       have] {analytic}{suffix}")
                skipped += 1
                continue

            try:
                result = client.submit_and_wait("heatmap", payload)
            except FortyGuardError as exc:
                # Keep going. One failed rung should not abandon the twelve calls
                # that already succeeded and were written.
                print(f"    [     FAILED] {analytic}{suffix}: {exc}", file=sys.stderr)
                continue

            # Named by request hash so a fixture lookup and a cache lookup resolve
            # identically — fixture mode then exercises the real code path rather
            # than a parallel one.
            FixtureStore(str(fixture_dir), strict=False).save(
                digest,
                "heatmap",
                payload,
                result.result,
                meta={
                    "district": district.key,
                    "district_name": district.name,
                    "analytic_type": analytic,
                    "threshold_c": threshold,
                    "activity_id": result.activity_id,
                    "captured_at": datetime.now(UTC).isoformat(),
                },
            )
            captured += 1
            print(f"    [   captured] {analytic}{suffix}  {target.name}")
    finally:
        client.close()

    print(f"\n  captured {captured}, already had {skipped}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--district", choices=sorted(DISTRICTS), help="Which district")
    parser.add_argument("--all", action="store_true", help="Every preset district")
    parser.add_argument("--list", action="store_true", help="List districts and exit")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fetched and what it costs, without spending",
    )
    parser.add_argument(
        "--tcm-only",
        action="store_true",
        help="Capture the temperature field only (1 call), not the full ladder",
    )
    parser.add_argument(
        "--granularity",
        type=int,
        choices=(60, 80, 100),
        help="Override the tile size; coarser keeps a large AOI's fixture small",
    )
    args = parser.parse_args(argv)

    if args.list:
        for district in DISTRICTS.values():
            print(f"{district.key:10} {district.name}")
        return 0

    targets = (
        list(DISTRICTS.values())
        if args.all
        else ([DISTRICTS[args.district]] if args.district else [])
    )
    if not targets:
        parser.error("choose --district NAME, or --all, or --list")

    for district in targets:
        code = harvest(
            district, dry_run=args.dry_run, tcm_only=args.tcm_only,
            granularity=args.granularity,
        )
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
