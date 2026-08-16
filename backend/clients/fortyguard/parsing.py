"""Parsing a completed heatmap result.

Written against the official API documentation at docs-api.fortyguard.com, which
confirms the completed-status payload as:

    data.result.map_data    GeoJSON FeatureCollection — tile polygons
    data.result.stats_data  aggregated statistics, with Temperature_stats holding
                            Minimum / Maximum / Mean / Standard_deviation

Two things follow, and the first is the more important.

**The API returns its own tiles.** We do not have to guess how our generated grid
lines up with theirs, and we must not: matching by array index would silently
mis-assign every temperature the moment their tiling differed from ours by one
cell. Each feature carries its own polygon, so the geometry is taken from the
response and the tile key is derived from that geometry's centroid. Our own grid
stays useful for pre-flight estimates, but it is not the thing values are attached
to.

**The per-feature value key is not documented.** `map_data` appears in the docs as
an empty placeholder, so the property holding a tile's temperature or hour count is
still unknown. A short list of likely names is tried; when none matches, the tile
gets `None`. That is the whole rule this project runs on — an empty layer with a
visible coverage figure is honest, a guessed one is a fabricated temperature field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import structlog

log = structlog.get_logger(__name__)

#: Candidate property names for a tile's value, most specific first. Extend this
#: once the live API shows which one it actually uses — do not add a fallback that
#: computes or defaults a value.
VALUE_KEYS: Final[tuple[str, ...]] = (
    "value",
    "temperature",
    "tcm",
    "hours",
    "count",
    "temp",
    "val",
)

#: Documented statistics block. Capitalised exactly as the API returns it — the
#: earlier lowercase guess silently read nothing and produced a null district mean.
TEMPERATURE_STATS_KEY: Final[str] = "Temperature_stats"

STAT_NAMES: Final[dict[str, str]] = {
    "min": "Minimum",
    "max": "Maximum",
    "mean": "Mean",
    "std": "Standard_deviation",
}


@dataclass(frozen=True, slots=True)
class ParsedTile:
    """One tile as the API returned it."""

    #: GeoJSON Polygon geometry, passed through untouched.
    geometry: dict[str, Any]
    west: float
    south: float
    east: float
    north: float
    centroid_lon: float
    centroid_lat: float
    #: None when the response carried no recognisable value for this tile.
    value: float | None


@dataclass(frozen=True, slots=True)
class ParsedHeatmap:
    tiles: list[ParsedTile]
    #: Which property name the values were read from, or None if none matched.
    value_key: str | None
    units: str | None

    @property
    def with_values(self) -> int:
        return sum(1 for tile in self.tiles if tile.value is not None)


def parse_heatmap(result: dict[str, Any]) -> ParsedHeatmap:
    """Turn `data.result` into tiles.

    Accepts the `result` object, not the whole envelope, because the client has
    already unwrapped `data.result` by the time this is called.
    """
    map_data = result.get("map_data")
    if not isinstance(map_data, dict):
        log.warning(
            "heatmap.no_map_data",
            keys=sorted(result)[:10],
            detail="result carried no map_data object; layer will be empty",
        )
        return ParsedHeatmap(tiles=[], value_key=None, units=_units(result))

    features = map_data.get("features")
    if not isinstance(features, list) or not features:
        log.warning("heatmap.no_features", detail="map_data has no features array")
        return ParsedHeatmap(tiles=[], value_key=None, units=_units(result))

    value_key = _detect_value_key(features)
    if value_key is None:
        log.warning(
            "heatmap.unrecognised_value_key",
            sample_properties=sorted(
                (features[0].get("properties") or {}).keys()
            )[:12],
            detail=(
                "no known property held a numeric value; tiles are recorded with "
                "geometry and a null value rather than a guessed one"
            ),
        )

    tiles: list[ParsedTile] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            continue

        bounds = _bounds(geometry)
        if bounds is None:
            continue
        west, south, east, north = bounds

        value: float | None = None
        if value_key is not None:
            raw = (feature.get("properties") or {}).get(value_key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                value = float(raw)

        tiles.append(
            ParsedTile(
                geometry=geometry,
                west=west,
                south=south,
                east=east,
                north=north,
                centroid_lon=(west + east) / 2.0,
                centroid_lat=(south + north) / 2.0,
                value=value,
            )
        )

    log.info(
        "heatmap.parsed",
        tiles=len(tiles),
        with_values=sum(1 for t in tiles if t.value is not None),
        value_key=value_key,
    )
    return ParsedHeatmap(tiles=tiles, value_key=value_key, units=_units(result))


def _detect_value_key(features: list[Any]) -> str | None:
    """Find which property carries the tile value.

    Decided once from a sample rather than per feature, so a single tile with an
    unusual property cannot switch the key mid-layer and mix two quantities into
    one column.
    """
    sample = [f for f in features[:25] if isinstance(f, dict)]

    for key in VALUE_KEYS:
        for feature in sample:
            raw = (feature.get("properties") or {}).get(key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                return key

    return None


def _bounds(geometry: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Bounding box of a Polygon or MultiPolygon, in degrees."""
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        return None

    lons: list[float] = []
    lats: list[float] = []

    def walk(node: Any) -> None:
        if (
            isinstance(node, list)
            and len(node) >= 2
            and all(isinstance(v, (int, float)) for v in node[:2])
        ):
            lons.append(float(node[0]))
            lats.append(float(node[1]))
            return
        if isinstance(node, list):
            for child in node:
                walk(child)

    walk(coordinates)
    if not lons or not lats:
        return None
    return min(lons), min(lats), max(lons), max(lats)


def _units(result: dict[str, Any]) -> str | None:
    """Units as the API reported them.

    Read rather than assumed: the docs state tcm returns °C while
    time_of_measure, exceedance and persistence return hours, and SRS C-4 records
    that documented and returned units have disagreed before.
    """
    stats = result.get("stats_data")
    if isinstance(stats, dict):
        raw = stats.get("units")
        if isinstance(raw, str):
            return raw
    return None


def read_stat(result: dict[str, Any], name: str) -> float | None:
    """One documented statistic from `stats_data.Temperature_stats`.

    `name` is a lowercase shorthand — min, max, mean, std — mapped to the
    capitalised keys the API actually returns. None when absent: a district mean
    of 0 °C would make every tile look extraordinarily hot.
    """
    stats = result.get("stats_data")
    if not isinstance(stats, dict):
        return None

    block = stats.get(TEMPERATURE_STATS_KEY)
    if not isinstance(block, dict):
        # Tolerated fallback: some responses may flatten the block. Read only the
        # documented capitalised key, never a lowercase guess.
        block = stats

    raw = block.get(STAT_NAMES.get(name, name))
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    return None
