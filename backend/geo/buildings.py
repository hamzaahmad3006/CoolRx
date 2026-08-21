"""Building footprint coverage per tile, from OpenStreetMap.

Populates one field:

    building_pct    share of the tile covered by mapped building footprints

No API key. Data comes from the Overpass API over OpenStreetMap.

## Licence — this is the one source with real obligations

Every other layer CoolRx reads is a US Government work in the public domain, where
attribution is a courtesy. **OpenStreetMap is ODbL**, which requires attribution
wherever OSM-derived data appears. CoolRx renders "© OpenStreetMap contributors" on
every map view and in every page footer of the Cooling Action Plan, and the position
on share-alike is recorded in `docs/DATA_LICENSES.md`.

## One query per AOI, and why that matters here

Overpass is a free, donated service with a fair-use policy, and it is the easiest of
CoolRx's upstreams to abuse. A per-tile query would mean ~1,200 requests per
diagnosis. Instead a single query returns every building in the AOI bounding box
with its geometry, and footprints are intersected against tiles locally.

It is also by far the least reliable upstream. It returned 504 on 2026-08-19,
answered a lightweight `out count;` query on 2026-08-21, and minutes later returned
504 from the main instance and 502 from the Kumi mirror for the `out geom;` query
this provider needs.

**So this provider has not yet been verified against a live response.** The code
path, the geometry handling and the failure behaviour are covered by tests, and a
transport failure produces misses rather than an exception — but unlike every other
provider here, no real Overpass payload has been parsed yet. That is recorded rather
than glossed, and it should be confirmed before the numbers are shown to anyone.

## Mapped, not built

`building_pct` measures **mapped** building coverage. OSM completeness varies by
place — dense in a well-surveyed city, sparse elsewhere — so a low value can mean
"few buildings" or "few contributors". The two are indistinguishable from the data.

Zero is therefore reported as zero only when the query succeeded and returned
buildings *somewhere* in the AOI; a query that finds nothing at all across the whole
area is treated as absent data and yields nulls, because a whole district with no
mapped buildings is far more likely to be an unmapped area than an empty one.
"""

from __future__ import annotations

from typing import Any, Final

import structlog

from . import _http
from .grid import Tile
from .providers import FeatureProvider, ProviderInfo, ProviderResult

log = structlog.get_logger(__name__)

OVERPASS_URL: Final[str] = "https://overpass-api.de/api/interpreter"

#: Vector data has no cell size.
_RESOLUTION_M: Final[float | None] = None

_TIMEOUT_SECONDS: Final[float] = 180.0

#: Overpass' own internal budget, kept below the HTTP timeout so the server
#: returns a partial answer rather than the connection dropping.
_QUERY_TIMEOUT_S: Final[int] = 120

#: Overpass returns **406 Not Acceptable** to the default `python-httpx` agent —
#: verified 2026-08-21, and it fails before the query is even parsed, so it looks
#: like a malformed request rather than a blocked client. Their usage policy also
#: asks callers to identify the application, which this does.
_USER_AGENT: Final[str] = (
    "CoolRx/1.0 (FortyGuard Hackathon 26; urban heat analysis)"
)


class BuildingFootprintProvider(FeatureProvider):
    """`building_pct` from OpenStreetMap building footprints."""

    def __init__(self, *, endpoint: str = OVERPASS_URL) -> None:
        self._endpoint = endpoint

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="osm_building_footprints",
            resolution_m=_RESOLUTION_M,
            source=(
                "OpenStreetMap building footprints via Overpass API "
                "(© OpenStreetMap contributors, ODbL)"
            ),
            vintage="live OSM extract",
        )

    @property
    def fields(self) -> tuple[str, ...]:
        return ("building_pct",)

    def is_available(self) -> bool:
        try:
            import shapely  # noqa: F401
        except ImportError:
            return False
        return True

    # ── the work ─────────────────────────────────────────────────────────────

    def fetch(self, tiles: list[Tile]) -> ProviderResult:
        result = ProviderResult(info=self.info)
        if not tiles:
            return result

        west = min(t.west for t in tiles)
        south = min(t.south for t in tiles)
        east = max(t.east for t in tiles)
        north = max(t.north for t in tiles)

        try:
            footprints = self._footprints(west, south, east, north)
        except Exception as exc:  # noqa: BLE001 — never raise on partial coverage
            reason = f"buildings unavailable: {type(exc).__name__}"
            log.warning("buildings.fetch_failed", error=str(exc))
            result.misses = {t.tile_key: reason for t in tiles}
            return result

        if not footprints:
            # An entire district with nothing mapped is far more likely to be
            # unsurveyed than genuinely empty, so this is absent data, not zero.
            reason = "no mapped buildings in the AOI — treated as unmapped, not empty"
            for tile in tiles:
                result.misses[tile.tile_key] = reason
                result.values[tile.tile_key] = {"building_pct": None}
            log.info("buildings.none_mapped", tiles=len(tiles))
            return result

        self._cover(tiles, footprints, result)
        return result

    def _footprints(
        self, west: float, south: float, east: float, north: float
    ) -> list[Any]:
        """Every mapped building in the bounding box, as shapely polygons."""
        import httpx
        from shapely.geometry import Polygon

        query = (
            f"[out:json][timeout:{_QUERY_TIMEOUT_S}];"
            f'(way["building"]({south},{west},{north},{east});'
            f'relation["building"]({south},{west},{north},{east}););'
            "out geom;"
        )
        response = _http.post(
            self._endpoint,
            data={"data": query},
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        polygons: list[Any] = []
        for element in response.json().get("elements", []):
            geometry = element.get("geometry")
            if not geometry or len(geometry) < 4:
                continue
            ring = [(p["lon"], p["lat"]) for p in geometry if "lon" in p]
            if len(ring) < 4:
                continue
            try:
                polygon = Polygon(ring)
                if not polygon.is_valid:
                    # Self-touching footprints are common in OSM; buffer(0) is
                    # the standard repair and is safe for area.
                    polygon = polygon.buffer(0)
            except Exception:  # noqa: BLE001 — one bad way is not fatal
                continue
            if not polygon.is_empty and polygon.area > 0:
                polygons.append(polygon)

        log.info("buildings.fetched", footprints=len(polygons))
        return polygons

    def _cover(
        self, tiles: list[Tile], footprints: list[Any], result: ProviderResult
    ) -> None:
        from shapely.geometry import box
        from shapely.strtree import STRtree

        index = STRtree(footprints)
        answered = 0

        for tile in tiles:
            cell = box(tile.west, tile.south, tile.east, tile.north)
            cell_area = cell.area
            if cell_area <= 0:
                result.misses[tile.tile_key] = "degenerate tile geometry"
                result.values[tile.tile_key] = {"building_pct": None}
                continue

            covered = 0.0
            for idx in index.query(cell):
                overlap = cell.intersection(footprints[idx]).area
                if overlap > 0:
                    covered += overlap

            # Footprints can overlap each other in OSM; the sum of intersections
            # can therefore exceed the tile. Capped rather than reported as
            # >100% coverage, which is not a thing.
            pct = min(100.0, 100.0 * covered / cell_area)
            result.values[tile.tile_key] = {"building_pct": round(pct, 2)}
            answered += 1

        log.info("buildings.covered", tiles=len(tiles), answered=answered)
