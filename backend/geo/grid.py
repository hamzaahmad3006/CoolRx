"""Tile grid generation.

The grid is built in UTM, not in degrees. That choice is load-bearing.

A degree-based grid has cells whose width in metres changes with latitude, so a
"60 m" tile would be 60 m tall and something else wide, and the person-heat-hours
figures — population × hours, summed over tiles — would be computed over cells of
unequal area. UTM is metre-based, so snapping the grid origin to a multiple of the
granularity produces cells that are actually square and actually the requested size.

Snapping also makes the grid **globally deterministic within a zone**: the same
ground location falls in the same cell regardless of where the AOI boundary was
drawn. Two overlapping projects therefore share tile keys for shared ground, which
is what lets `tile_features` and `exposure` be reused across projects rather than
recomputed per AOI.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

import structlog
from pyproj import CRS, Transformer

from .tilekey import tile_key

log = structlog.get_logger(__name__)

#: The API accepts only these, in metres.
VALID_GRANULARITIES: Final[tuple[int, ...]] = (60, 80, 100)

#: Refuse to build a grid larger than this. A 10 mi² AOI at 60 m is ~7,200 tiles;
#: this ceiling is roughly the 50 mi² Premium cap at the same granularity, and
#: exists so a malformed bounding box cannot try to allocate millions of rows.
MAX_TILES: Final[int] = 40_000


@dataclass(frozen=True, slots=True)
class Tile:
    """One grid cell. Bounds are WGS84 degrees; the centroid drives the key."""

    tile_key: str
    west: float
    south: float
    east: float
    north: float
    centroid_lon: float
    centroid_lat: float


@dataclass(frozen=True, slots=True)
class GridSpec:
    """What was built, for logging and provenance."""

    granularity_m: int
    utm_epsg: int
    columns: int
    rows: int
    tile_count: int
    #: True when the AOI spans more than one UTM zone and one zone was used for
    #: all of it. At district scale the distortion is negligible, but it is
    #: recorded rather than hidden.
    spans_utm_zones: bool


def utm_epsg_for(longitude: float, latitude: float) -> int:
    """EPSG code of the UTM zone containing this coordinate.

    326xx north of the equator, 327xx south.
    """
    if not -180.0 <= longitude <= 180.0:
        raise ValueError(f"longitude {longitude} is outside [-180, 180]")
    if not -90.0 <= latitude <= 90.0:
        raise ValueError(f"latitude {latitude} is outside [-90, 90]")

    zone = int(math.floor((longitude + 180.0) / 6.0)) + 1
    # Longitude exactly 180° lands in zone 61 by that formula; it belongs in 60.
    zone = min(zone, 60)
    return (32600 if latitude >= 0 else 32700) + zone


def _zone_of(longitude: float) -> int:
    return min(int(math.floor((longitude + 180.0) / 6.0)) + 1, 60)


def build_grid(
    *,
    west: float,
    south: float,
    east: float,
    north: float,
    granularity_m: int,
) -> tuple[list[Tile], GridSpec]:
    """Tile a bounding box.

    Returns tiles whose union covers the box. Cells are snapped to a multiple of
    `granularity_m` in UTM, so the grid extends to or slightly beyond the requested
    edges rather than clipping a partial cell — a half-width cell would carry half
    the population of its neighbours and skew every per-tile figure.
    """
    if granularity_m not in VALID_GRANULARITIES:
        raise ValueError(
            f"granularity must be one of {VALID_GRANULARITIES}, got {granularity_m}"
        )
    if west >= east:
        raise ValueError(f"west ({west}) must be less than east ({east})")
    if south >= north:
        raise ValueError(f"south ({south}) must be less than north ({north})")

    centre_lon = (west + east) / 2.0
    centre_lat = (south + north) / 2.0
    epsg = utm_epsg_for(centre_lon, centre_lat)
    spans_zones = _zone_of(west) != _zone_of(east)

    if spans_zones:
        # Not an error: at ≤50 mi² the cross-zone distortion is far below the
        # 60 m cell size. Logged so it is visible if a result ever looks skewed.
        log.info(
            "grid.spans_utm_zones",
            west_zone=_zone_of(west),
            east_zone=_zone_of(east),
            using_epsg=epsg,
        )

    to_utm = Transformer.from_crs(CRS.from_epsg(4326), CRS.from_epsg(epsg), always_xy=True)
    to_wgs = Transformer.from_crs(CRS.from_epsg(epsg), CRS.from_epsg(4326), always_xy=True)

    # Project all four corners, not two. A UTM grid is not axis-aligned with a
    # lat/lon box, so using only the SW and NE corners would clip the two corners
    # that bow outward.
    corners = [
        to_utm.transform(west, south),
        to_utm.transform(east, south),
        to_utm.transform(east, north),
        to_utm.transform(west, north),
    ]
    xs = [x for x, _ in corners]
    ys = [y for _, y in corners]

    step = float(granularity_m)
    x_start = math.floor(min(xs) / step) * step
    x_end = math.ceil(max(xs) / step) * step
    y_start = math.floor(min(ys) / step) * step
    y_end = math.ceil(max(ys) / step) * step

    columns = int(round((x_end - x_start) / step))
    rows = int(round((y_end - y_start) / step))
    count = columns * rows

    if count > MAX_TILES:
        raise ValueError(
            f"grid would contain {count:,} tiles, above the {MAX_TILES:,} ceiling; "
            f"reduce the area or use a coarser granularity than {granularity_m} m"
        )
    if count == 0:
        raise ValueError("bounding box produced an empty grid")

    tiles = list(
        _emit_tiles(
            to_wgs=to_wgs,
            x_start=x_start,
            y_start=y_start,
            step=step,
            columns=columns,
            rows=rows,
        )
    )

    spec = GridSpec(
        granularity_m=granularity_m,
        utm_epsg=epsg,
        columns=columns,
        rows=rows,
        tile_count=len(tiles),
        spans_utm_zones=spans_zones,
    )
    log.info(
        "grid.built",
        tiles=len(tiles),
        columns=columns,
        rows=rows,
        epsg=epsg,
        granularity_m=granularity_m,
    )
    return tiles, spec


def _emit_tiles(
    *,
    to_wgs: Transformer,
    x_start: float,
    y_start: float,
    step: float,
    columns: int,
    rows: int,
) -> Iterator[Tile]:
    for row in range(rows):
        y0 = y_start + row * step
        y1 = y0 + step
        for column in range(columns):
            x0 = x_start + column * step
            x1 = x0 + step

            # All four corners are unprojected. A UTM square maps to a slightly
            # rotated quadrilateral in degrees, so taking min/max across the four
            # gives the true degree extent rather than an under-covering box.
            sw = to_wgs.transform(x0, y0)
            se = to_wgs.transform(x1, y0)
            ne = to_wgs.transform(x1, y1)
            nw = to_wgs.transform(x0, y1)
            lons = (sw[0], se[0], ne[0], nw[0])
            lats = (sw[1], se[1], ne[1], nw[1])

            centre_lon, centre_lat = to_wgs.transform(
                x0 + step / 2.0, y0 + step / 2.0
            )

            yield Tile(
                tile_key=tile_key(centre_lon, centre_lat),
                west=min(lons),
                south=min(lats),
                east=max(lons),
                north=max(lats),
                centroid_lon=centre_lon,
                centroid_lat=centre_lat,
            )


def estimate_tile_count(
    *, west: float, south: float, east: float, north: float, granularity_m: int
) -> int:
    """Tile count without building the grid.

    Used by the AOI Studio to warn before a request, and by `build_grid`'s callers
    to size a batch. Cheap because it projects four corners rather than N cells.
    """
    centre_lon = (west + east) / 2.0
    centre_lat = (south + north) / 2.0
    epsg = utm_epsg_for(centre_lon, centre_lat)
    to_utm = Transformer.from_crs(
        CRS.from_epsg(4326), CRS.from_epsg(epsg), always_xy=True
    )
    corners = [
        to_utm.transform(west, south),
        to_utm.transform(east, south),
        to_utm.transform(east, north),
        to_utm.transform(west, north),
    ]
    xs = [x for x, _ in corners]
    ys = [y for _, y in corners]
    step = float(granularity_m)
    columns = int(math.ceil(max(xs) / step) - math.floor(min(xs) / step))
    rows = int(math.ceil(max(ys) / step) - math.floor(min(ys) / step))
    return columns * rows
