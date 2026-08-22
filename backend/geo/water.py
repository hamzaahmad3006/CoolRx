"""Distance from each tile to the nearest open water.

Populates one field:

    dist_to_water_m    straight-line distance to the nearest perennial water feature

No API key. Water comes from the USGS National Hydrography Dataset (NHD), served
as vector features by hydro.nationalmap.gov.

## Why not the NLCD raster

This provider previously took water from the same NLCD coverage `geo/landcover.py`
reads, so the two features could not disagree about where water is. That was tidy
and unusably slow. Water serving a district is frequently outside it, so the
coverage had to be fetched over the AOI expanded by 10 km — roughly 445,000 cells
at 30 m — and on 2026-08-21 that request ran for over twenty minutes without
returning, having already failed once with a read timeout at four minutes.

The same question asked of NHD as a vector query answers in about two seconds.
A distance measured in kilometres does not need a 30 m raster of an entire county
to compute; it needs the geometry of the nearest few water features.

`water_pct` still comes from NLCD, so the two can now in principle disagree at
the margins. They answer different questions — "how much of this tile is water"
against "how far to the nearest water" — and the second is the one that needs to
see beyond the tile.

## Which NHD features count as water

This matters more in an arid city than anywhere else. Of the 188 flowlines NHD
returns within 10 km of downtown Phoenix, only **four** are perennial streams:

    46006  Stream/River, Perennial     4      included
    33600  Canal/Ditch               127      included, see below
    46007  Stream/River, Ephemeral    18      excluded — dry most of the year
    55800  Artificial Path            30      excluded — a routing line through
                                              a waterbody, not itself water
    42813  Pipeline                    4      excluded — not open water
    33400  Connector                   3      excluded — a topological link

Taking every flowline would have counted pipelines and routing lines as rivers
and treated dry desert washes as cooling features. An ephemeral wash is bare
sand for most of the cooling season; recording a tile as 200 m from water because
a wash runs past it would put a wrong number into a model that predicts how much
cooler a street gets.

**Canals are included, and that is a judgement rather than a fact.** In Phoenix
the SRP canals carry water year-round and are genuinely the dominant open water
in the built-up area, so excluding them would be the larger error. Nationally,
`Canal/Ditch` also covers irrigation ditches that are dry much of the year. The
choice is recorded in `info.source` so a reviewer can see it and disagree.

Waterbodies use the same reasoning: lakes, ponds and reservoirs count;
intermittent and ephemeral ones do not.

## The search window, and why the answer is sometimes null

The query covers the AOI expanded by a buffer (default 10 km). If no qualifying
feature appears in that window the field is **null, not a large number**. A tile
10 km from water and one 60 km from it would both need a figure this method
cannot produce, and a floor value would be a fabricated distance in a feature the
model trains on. The miss records the radius searched, so "null" reads as "no
perennial water within 10 km" rather than as an unexplained gap.

## Distance is measured on the ground

Tile centroids and water geometry are projected to the AOI's UTM zone before any
distance is taken, so the result is true metres. Measuring in degrees would
overstate every east-west distance by about 20% at Phoenix's latitude, where a
degree of longitude is ~93 km rather than 111 km.
"""

from __future__ import annotations

from typing import Any, Final

import structlog

from . import _http
from .grid import Tile, utm_epsg_for
from .providers import FeatureProvider, ProviderInfo, ProviderResult

log = structlog.get_logger(__name__)

NHD_SERVICE: Final[str] = (
    "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer"
)

#: Layer ids on that service.
FLOWLINE_LAYER: Final[int] = 6
WATERBODY_LAYER: Final[int] = 10

#: Flowline FCODEs that carry water for most of the cooling season.
#: 46006 perennial stream/river; 33600/33601/33603 canal/ditch — see the module
#: docstring for why canals are in and ephemeral washes are out.
PERENNIAL_FLOWLINE_FCODES: Final[frozenset[int]] = frozenset(
    {46006, 33600, 33601, 33603}
)

#: Waterbody FCODEs. 39004 lake/pond perennial, 39009/39010 perennial variants,
#: 43600-series reservoirs. Intermittent (39001) and ephemeral bodies are out.
PERENNIAL_WATERBODY_FCODES: Final[frozenset[int]] = frozenset(
    {39004, 39009, 39010, 39011, 39012, 43600, 43601, 43603, 43604,
     43605, 43606, 43607, 43608, 43609, 43610, 43611, 43612, 43613,
     43614, 43615, 43617, 43618, 43619, 43621, 43623, 43624, 43625, 43626}
)

#: How far beyond the AOI to look. Water that cools a district is frequently
#: outside it.
DEFAULT_SEARCH_BUFFER_M: Final[float] = 10_000.0

_DEG_PER_M_LAT: Final[float] = 1.0 / 111_320.0

_TIMEOUT_SECONDS: Final[float] = 90.0


class WaterDistanceProvider(FeatureProvider):
    """`dist_to_water_m` from NHD perennial water geometry."""

    def __init__(
        self,
        *,
        search_buffer_m: float = DEFAULT_SEARCH_BUFFER_M,
        service: str = NHD_SERVICE,
    ) -> None:
        self._buffer_m = search_buffer_m
        self._service = service

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="nhd_water_distance",
            resolution_m=None,
            source=(
                "Distance to nearest perennial water, USGS National Hydrography "
                "Dataset via hydro.nationalmap.gov. Includes perennial "
                "streams/rivers (FCODE 46006), canals and ditches (33600 series) "
                "and perennial lakes, ponds and reservoirs. Excludes ephemeral "
                "and intermittent watercourses, pipelines and artificial paths. "
                "Canals are included because in an arid city they are the "
                "dominant year-round open water; elsewhere some carry water only "
                "seasonally. Searched within "
                f"{int(self._buffer_m / 1000)} km of the AOI"
            ),
            vintage="NHD dynamic service",
        )

    @property
    def fields(self) -> tuple[str, ...]:
        return ("dist_to_water_m",)

    def is_available(self) -> bool:
        try:
            import pyproj  # noqa: F401
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
            geometries = self._water_geometries(west, south, east, north)
        except Exception as exc:  # noqa: BLE001 — never raise on partial coverage
            reason = f"water distance unavailable: {type(exc).__name__}"
            log.warning("water.fetch_failed", error=str(exc))
            result.misses = {t.tile_key: reason for t in tiles}
            return result

        if not geometries:
            reason = (
                f"no perennial water within {int(self._buffer_m / 1000)} km of "
                f"the AOI"
            )
            for tile in tiles:
                result.misses[tile.tile_key] = reason
                result.values[tile.tile_key] = {"dist_to_water_m": None}
            log.info("water.no_water_in_window", tiles=len(tiles))
            return result

        from shapely.ops import unary_union

        # Project the water once, not once per tile. Reprojecting the union
        # inside the loop made a 34,640-tile training run take longer than an
        # hour for a calculation that takes seconds -- shapely does the geometry
        # work quickly, and pyproj was being asked to redo all of it 11,000 times
        # per district.
        try:
            water = self._to_utm(
                unary_union(geometries), (west + east) / 2, (south + north) / 2
            )
        except Exception as exc:  # noqa: BLE001 — a projection failure is a miss
            log.warning("water.projection_failed", error=str(exc))
            reason = f"water distance unavailable: {type(exc).__name__}"
            result.misses = {t.tile_key: reason for t in tiles}
            return result

        answered = 0
        for tile in tiles:
            value = self._distance(water, tile, (west + east) / 2, (south + north) / 2)
            if value is None:
                result.misses[tile.tile_key] = "could not project this tile"
                result.values[tile.tile_key] = {"dist_to_water_m": None}
            else:
                result.values[tile.tile_key] = {"dist_to_water_m": value}
                answered += 1

        log.info(
            "water.parsed",
            tiles=len(tiles),
            answered=answered,
            features=len(geometries),
        )
        return result

    # ── NHD ──────────────────────────────────────────────────────────────────

    def _water_geometries(
        self, west: float, south: float, east: float, north: float
    ) -> list[Any]:
        """Qualifying water geometry within the buffered AOI, in EPSG:4326."""
        mid_lat = (south + north) / 2.0
        pad_lat = self._buffer_m * _DEG_PER_M_LAT
        # A degree of longitude shortens with latitude; without this the buffer
        # would be narrower east-west than intended.
        import math

        pad_lon = pad_lat / max(0.1, math.cos(math.radians(mid_lat)))

        envelope = (
            f"{west - pad_lon},{south - pad_lat},"
            f"{east + pad_lon},{north + pad_lat}"
        )

        geometries: list[Any] = []
        geometries += self._query(
            FLOWLINE_LAYER, envelope, "fcode", PERENNIAL_FLOWLINE_FCODES
        )
        geometries += self._query(
            WATERBODY_LAYER, envelope, "FCODE", PERENNIAL_WATERBODY_FCODES
        )
        return geometries

    def _query(
        self, layer: int, envelope: str, fcode_field: str, keep: frozenset[int]
    ) -> list[Any]:
        """One layer's qualifying features as shapely geometries.

        The FCODE filter is applied server-side so the payload carries only water
        that counts, and re-checked here because a service that ignores an
        unsupported `where` would otherwise return everything silently.
        """
        codes = ",".join(str(c) for c in sorted(keep))
        params = {
            "geometry": envelope,
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "where": f"{fcode_field} IN ({codes})",
            "outFields": fcode_field,
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
        }
        response = _http.get(
            f"{self._service}/{layer}/query",
            params=params,
            timeout=_TIMEOUT_SECONDS,
            provider="nhd",
        )
        response.raise_for_status()
        payload = response.json()

        if "error" in payload:
            raise ValueError(f"NHD error: {payload['error']}")

        from shapely.geometry import LineString, Polygon

        geometries: list[Any] = []
        for feature in payload.get("features", []):
            attributes = feature.get("attributes") or {}
            code = attributes.get(fcode_field)
            if code is not None and int(code) not in keep:
                continue

            geometry = feature.get("geometry") or {}
            for ring in geometry.get("rings", []):
                if len(ring) >= 4:
                    try:
                        geometries.append(Polygon(ring))
                    except Exception:  # noqa: BLE001 — one bad ring is not fatal
                        continue
            for path in geometry.get("paths", []):
                if len(path) >= 2:
                    try:
                        geometries.append(LineString(path))
                    except Exception:  # noqa: BLE001
                        continue

        return geometries

    # ── distance ─────────────────────────────────────────────────────────────

    def _to_utm(self, geometry: Any, mid_lon: float, mid_lat: float) -> Any:
        """Reproject one geometry into the AOI's UTM zone.

        Shapely measures in whatever units it is given, and in degrees an
        east-west distance is understated by about a fifth at Phoenix's latitude.
        """
        from pyproj import Transformer
        from shapely.ops import transform

        epsg = utm_epsg_for(mid_lon, mid_lat)
        self._transformer = Transformer.from_crs(
            "EPSG:4326", f"EPSG:{epsg}", always_xy=True
        )
        return transform(self._transformer.transform, geometry)

    def _distance(
        self, water_utm: Any, tile: Tile, mid_lon: float, mid_lat: float
    ) -> float | None:
        """Metres from the tile centroid to the nearest water geometry.

        `water_utm` is already projected; only the single centroid point is
        transformed here.
        """
        try:
            from shapely.geometry import Point

            x, y = self._transformer.transform(
                tile.centroid_lon, tile.centroid_lat
            )
            return round(float(water_utm.distance(Point(x, y))), 1)
        except Exception as exc:  # noqa: BLE001 — a projection failure is a miss
            log.warning("water.projection_failed", error=str(exc))
            return None
