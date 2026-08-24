"""Create the preset demo districts, matching the captured fixtures.

    python -m scripts.seed_presets           # create or update
    python -m scripts.seed_presets --check   # report, write nothing

The landing page offers a district to click. Until now it offered three that did
not exist: `phoenix-encanto`, `la-westlake`, `houston-gulfton`, carrying
hard-coded statistics — 44.1 °C, 12,400 people — that came from nowhere. No
fixture backs them, no measurement produced them, and clicking one asked the
backend for a project id it had never issued, which is what the 422s were.

They are replaced by the three districts actually captured from FortyGuard, whose
AOIs are copied from `harvest_fixtures.DISTRICTS` so the seeded project and the
recorded response describe the same ground. A preset whose AOI drifted from its
fixture would run live and spend credits during a demo.

Statistics are not seeded. They come from running a diagnosis, which is the point
of the product.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import structlog
from sqlalchemy import select

from repositories.base import session_scope
from repositories.projects import ProjectRepository
from repositories.tables import Project
from scripts.harvest_fixtures import DISTRICTS, District

log = structlog.get_logger(__name__)

#: Only the small district captures are seeded. The `_city` AOIs exist to give
#: the model land-cover contrast to train on; they carry a `tcm` field and none
#: of the eleven exceedance rungs, so a diagnosis over one would have no ladder
#: and could not produce a plan.
PRESET_KEYS: tuple[str, ...] = ("phoenix", "lasvegas", "tucson")


def _aoi(district: District) -> dict[str, Any]:
    """The AOI as a bare GeoJSON geometry.

    `projects.aoi` is a PostGIS geometry column, not JSONB, so it takes the
    polygon rather than the FeatureCollection the HTTP API accepts. The API's own
    adapter unwraps the collection before it reaches the repository.
    """
    return {
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
    }


def _area_sqmi(district: District) -> float:
    """Planar approximation, adequate for a label on a card."""
    import math

    mid_lat = (district.south + district.north) / 2.0
    km_x = (district.east - district.west) * 111.32 * math.cos(math.radians(mid_lat))
    km_y = (district.north - district.south) * 111.32
    return round(km_x * km_y * 0.386102, 3)


def seed(*, check_only: bool) -> int:
    created, updated, present = [], [], []

    with session_scope() as session:
        for key in PRESET_KEYS:
            district = DISTRICTS[key]
            existing = session.execute(
                select(Project).where(
                    Project.name == district.name, Project.is_preset.is_(True)
                )
            ).scalars().first()

            if existing is not None:
                present.append((district.name, str(existing.id)))
                if not check_only:
                    # Left as-is. Rewriting the geometry of a preset that already
                    # has analytic runs against it would silently decouple the
                    # stored tiles from the AOI they were measured over.
                    updated.append(district.name)
                continue

            if check_only:
                created.append(district.name)
                continue

            project = ProjectRepository(session).create(
                name=district.name,
                city=district.name.split(",")[0].replace("Central ", "").strip(),
                state=district.name.strip()[-2:],
                aoi_geojson=_aoi(district),
                area_sqmi=_area_sqmi(district),
                is_preset=True,
            )
            created.append(district.name)
            present.append((district.name, str(project.id)))

    print("CoolRx · preset districts")
    for name, project_id in present:
        print(f"  {name:28s} {project_id}")
    if check_only:
        print(f"\n  would create {len(created)}, {len(present)} already present")
    else:
        print(f"\n  created {len(created)}, refreshed {len(updated)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="report and exit, writing nothing"
    )
    args = parser.parse_args(argv)
    try:
        return seed(check_only=args.check)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
