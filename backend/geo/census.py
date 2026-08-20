"""Population and age exposure, apportioned from census block groups.

Populates two fields on `exposure`:

    population    dasymetric estimate, block-group population shared onto tiles
    pct_over65    share of that population aged 65+, from ACS 5-year

Needs `CENSUS_API_KEY`. Free from <https://api.census.gov/data/key_signup.html>.
Without one the provider reports itself unavailable and both fields stay null —
the ACS endpoint began requiring a key at some point before 2026-08-18, which is
not what SRS §12.2 assumed when it listed ACS as open.

## Two services, no key on the first

Boundaries come from **TIGERweb** (`tigerweb.geo.census.gov`), which serves block
group polygons as GeoJSON and needs no key. Attributes come from the **ACS 5-year
API**, which does. Verified on the Phoenix AOI 2026-08-19: three block groups
intersect it, holding 1,929 / 2,026 / 2,654 people.

## Why the numbers are not integers

A tile is not a census unit. Population is apportioned by **areal share**: a tile
covering 30% of a block group receives 30% of its people. So a tile's population is
a continuous estimate, never a headcount, and `ExposureResponse.population` is typed
`float` for exactly that reason.

Areal apportionment conserves total population by construction — the sum over tiles
equals the block-group total wherever tiles cover it — which is what AC-04 checks.

**It assumes people are spread evenly within a block group, and they are not.** A
true dasymetric method would weight by where buildings actually are; `impervious_pct`
from `geo/mrlc.py` is the obvious weight and is the documented next refinement. The
flat assumption is stated here, in the schema, and on the Methods page rather than
buried, because it is the largest single source of error in the exposure figures.

## Why poverty is missing

`pct_poverty` is deliberately not populated. ACS publishes `B17001_002E` (income
below poverty) at **tract** level, not block group — verified: the block-group query
returns `null` for every row. Reporting a tract figure through a provider that
declares block-group resolution would misrepresent how precise it is, the same way
the SRS insists SVI be labelled at its true tract resolution. It needs its own
provider with its own declared resolution.
"""

from __future__ import annotations

from typing import Any, Final

import structlog

from .grid import Tile
from .providers import FeatureProvider, ProviderInfo, ProviderResult

log = structlog.get_logger(__name__)

TIGERWEB_BLOCKGROUP_URL: Final[str] = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
    "tigerWMS_ACS2023/MapServer/10/query"
)
ACS_URL: Final[str] = "https://api.census.gov/data/{year}/acs/acs5"

#: Total population.
_POPULATION_VAR: Final[str] = "B01003_001E"

#: Sex-by-age, the 65+ brackets. Twelve variables because ACS splits by sex and by
#: five-year band; there is no single "65 and over" figure in the detailed tables.
_OVER65_VARS: Final[tuple[str, ...]] = (
    "B01001_020E", "B01001_021E", "B01001_022E",
    "B01001_023E", "B01001_024E", "B01001_025E",
    "B01001_044E", "B01001_045E", "B01001_046E",
    "B01001_047E", "B01001_048E", "B01001_049E",
)

_TIMEOUT_SECONDS: Final[float] = 90.0


class CensusExposureProvider(FeatureProvider):
    """Block-group population and age, areally apportioned onto tiles."""

    def __init__(
        self,
        *,
        api_key: str | None,
        year: int = 2023,
        dasymetric: bool = True,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._year = year
        #: Weight population by built-up surface rather than spreading it evenly.
        #: Falls back to areal share per block group when the weight surface is
        #: unavailable or a group contains no built area at all.
        self._dasymetric = dasymetric

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="census_acs_exposure",
            # Block groups vary hugely in size; there is no single cell size, and
            # claiming one would imply a precision the source does not have.
            resolution_m=None,
            source=(
                f"US Census ACS {self._year} 5-year (block group) via api.census.gov, "
                "boundaries from TIGERweb; "
                + (
                    "dasymetric, weighted by NLCD impervious surface"
                    if self._dasymetric
                    else "areally apportioned to tiles"
                )
            ),
            vintage=f"ACS {self._year} 5-year",
        )

    @property
    def fields(self) -> tuple[str, ...]:
        return ("population", "pct_over65")

    def is_available(self) -> bool:
        """A key is required. Reported once, up front, rather than as 1,200 misses."""
        if not self._api_key:
            log.info("census.unavailable", reason="CENSUS_API_KEY is not set")
            return False
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

        if not self.is_available():
            reason = "census exposure unavailable: CENSUS_API_KEY not set"
            result.misses = {t.tile_key: reason for t in tiles}
            return result

        west = min(t.west for t in tiles)
        south = min(t.south for t in tiles)
        east = max(t.east for t in tiles)
        north = max(t.north for t in tiles)

        try:
            groups = self._block_groups(west, south, east, north)
            if not groups:
                raise ValueError("no block groups intersect the AOI")
            attributes = self._acs_attributes(groups)
        except Exception as exc:  # noqa: BLE001 — never raise on partial coverage
            reason = f"census exposure unavailable: {type(exc).__name__}"
            log.warning("census.fetch_failed", error=str(exc))
            result.misses = {t.tile_key: reason for t in tiles}
            return result

        weights: dict[str, dict[str, float]] | None = None
        if self._dasymetric:
            try:
                weights = self._weight_shares(tiles, groups)
            except Exception as exc:  # noqa: BLE001 — degrade, never fail
                log.warning("census.weights_unavailable", error=str(exc))
                weights = None

        self._apportion(tiles, groups, attributes, result, weights)
        return result

    def _weight_shares(
        self, tiles: list[Tile], groups: list[dict[str, Any]]
    ) -> dict[str, dict[str, float]]:
        """GEOID -> {tile_key: share of that block group's built area}.

        Shares are normalised over the **whole** block group, including the part
        outside the study area, so a group lying mostly beyond the AOI hands over
        only the fraction of its residents that actually live inside.

        Every share for a group therefore sums to at most 1, not exactly 1.
        """
        from shapely.geometry import box, shape
        from shapely.strtree import STRtree

        from .mrlc import fetch_percent_raster

        geometries: list[Any] = []
        geoids: list[str] = []
        for feature in groups:
            geoid = (feature.get("properties") or {}).get("GEOID")
            if not geoid:
                continue
            geometry = shape(feature["geometry"])
            if geometry.is_empty:
                continue
            geometries.append(geometry)
            geoids.append(str(geoid))

        if not geometries:
            raise ValueError("no usable block-group geometry")

        west = min(g.bounds[0] for g in geometries)
        south = min(g.bounds[1] for g in geometries)
        east = max(g.bounds[2] for g in geometries)
        north = max(g.bounds[3] for g in geometries)

        dataset, band = fetch_percent_raster(west, south, east, north)

        tile_geoms = [box(t.west, t.south, t.east, t.north) for t in tiles]
        tile_index = STRtree(tile_geoms)
        group_index = STRtree(geometries)

        totals: dict[str, float] = {g: 0.0 for g in geoids}
        shares: dict[str, dict[str, float]] = {g: {} for g in geoids}

        with dataset:
            rows, cols = band.shape
            for row in range(rows):
                for col in range(cols):
                    weight = float(band[row, col])
                    # 0 built area contributes nothing; >100 is a fill code.
                    if weight <= 0.0 or weight > 100.0:
                        continue
                    lon, lat = dataset.xy(row, col)
                    from shapely.geometry import Point

                    point = Point(lon, lat)

                    hit_geoid: str | None = None
                    for idx in group_index.query(point):
                        if geometries[idx].contains(point):
                            hit_geoid = geoids[idx]
                            break
                    if hit_geoid is None:
                        continue

                    # Denominator: the whole block group, AOI or not.
                    totals[hit_geoid] += weight

                    for idx in tile_index.query(point):
                        if tile_geoms[idx].contains(point):
                            key = tiles[idx].tile_key
                            shares[hit_geoid][key] = (
                                shares[hit_geoid].get(key, 0.0) + weight
                            )
                            break

        out: dict[str, dict[str, float]] = {}
        for geoid, total in totals.items():
            if total <= 0.0:
                # A block group with no built surface at all — a park, say.
                # Areal share is the honest fallback; zeroing it would delete
                # residents who demonstrably exist.
                continue
            out[geoid] = {
                key: value / total for key, value in shares[geoid].items()
            }

        log.info(
            "census.weights_built",
            groups=len(out),
            fallback_groups=len(totals) - len(out),
        )
        return out

    def _block_groups(
        self, west: float, south: float, east: float, north: float
    ) -> list[dict[str, Any]]:
        """Block-group polygons intersecting the AOI. No key needed."""
        import httpx

        params = {
            "where": "1=1",
            "geometry": f"{west},{south},{east},{north}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "GEOID,STATE,COUNTY,TRACT,BLKGRP",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
        }
        response = httpx.get(
            TIGERWEB_BLOCKGROUP_URL, params=params, timeout=_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return response.json().get("features") or []

    def _acs_attributes(
        self, groups: list[dict[str, Any]]
    ) -> dict[str, dict[str, float | None]]:
        """GEOID → {population, pct_over65}, one ACS request per tract.

        Batched by tract because ACS cannot wildcard block groups across tracts:
        `for=block group:*` requires `in=...tract:<one tract>`.
        """
        import httpx

        tracts: set[tuple[str, str, str]] = set()
        for feature in groups:
            p = feature.get("properties") or {}
            if p.get("STATE") and p.get("COUNTY") and p.get("TRACT"):
                tracts.add((p["STATE"], p["COUNTY"], p["TRACT"]))

        variables = ",".join((_POPULATION_VAR, *_OVER65_VARS))
        out: dict[str, dict[str, float | None]] = {}

        for state, county, tract in sorted(tracts):
            params = {
                "get": variables,
                "for": "block group:*",
                "in": f"state:{state} county:{county} tract:{tract}",
                "key": self._api_key,
            }
            response = httpx.get(
                ACS_URL.format(year=self._year),
                params=params,
                timeout=_TIMEOUT_SECONDS,
            )
            if response.status_code == 204:
                # Valid request, no rows for that geography. Not an error.
                continue
            response.raise_for_status()

            rows = response.json()
            header, *body = rows
            index = {name: i for i, name in enumerate(header)}

            for row in body:
                geoid = (
                    row[index["state"]]
                    + row[index["county"]]
                    + row[index["tract"]]
                    + row[index["block group"]]
                )
                population = _number(row[index[_POPULATION_VAR]])
                over65 = 0.0
                seen = False
                for var in _OVER65_VARS:
                    value = _number(row[index[var]])
                    if value is not None:
                        over65 += value
                        seen = True

                pct = None
                if seen and population:
                    pct = round(over65 / population, 4)

                out[geoid] = {"population": population, "pct_over65": pct}

        return out

    def _apportion(
        self,
        tiles: list[Tile],
        groups: list[dict[str, Any]],
        attributes: dict[str, dict[str, float | None]],
        result: ProviderResult,
        weights: dict[str, dict[str, float]] | None = None,
    ) -> None:
        """Share each block group's people across the tiles that overlap it.

        Uses the dasymetric weights where a group has them, and areal share
        where it does not — decided per group, not per run, so one park with no
        built surface does not force the whole AOI back onto the cruder method.
        """
        from shapely.geometry import box, shape

        weights = weights or {}
        prepared: list[tuple[Any, float, dict[str, float | None], str]] = []
        for feature in groups:
            geoid = str((feature.get("properties") or {}).get("GEOID"))
            attrs = attributes.get(geoid)
            if attrs is None:
                continue
            try:
                geometry = shape(feature["geometry"])
            except Exception:  # noqa: BLE001 — a malformed polygon is skipped
                continue
            if geometry.is_empty or geometry.area <= 0:
                continue
            prepared.append((geometry, geometry.area, attrs, geoid))

        if not prepared:
            for tile in tiles:
                result.misses[tile.tile_key] = "no block group attributes for the AOI"
                result.values[tile.tile_key] = {"population": None, "pct_over65": None}
            return

        answered = 0
        for tile in tiles:
            cell = box(tile.west, tile.south, tile.east, tile.north)
            population = 0.0
            weighted_over65 = 0.0
            matched = False

            for geometry, area, attrs, geoid in prepared:
                bg_population = attrs.get("population")
                if bg_population is None:
                    continue

                weighted = weights.get(geoid)
                if weighted is not None:
                    fraction = weighted.get(tile.tile_key)
                    if not fraction:
                        continue
                else:
                    if not cell.intersects(geometry):
                        continue
                    overlap = cell.intersection(geometry).area
                    if overlap <= 0:
                        continue
                    fraction = overlap / area

                share = bg_population * fraction
                population += share
                matched = True

                pct = attrs.get("pct_over65")
                if pct is not None:
                    weighted_over65 += share * pct

            if not matched:
                result.misses[tile.tile_key] = "tile intersects no block group"
                result.values[tile.tile_key] = {"population": None, "pct_over65": None}
                continue

            result.values[tile.tile_key] = {
                "population": round(population, 2),
                # Population-weighted, so a tile straddling two block groups gets
                # the mix its people actually come from, not a flat average.
                "pct_over65": (
                    round(weighted_over65 / population, 4) if population > 0 else None
                ),
            }
            answered += 1

        log.info("census.apportioned", tiles=len(tiles), answered=answered)


def _number(raw: Any) -> float | None:
    """ACS sends strings, and `null` for a figure not published at this geography.

    Negative values are ACS annotation codes (-666666666 and friends), not
    measurements, so they are discarded rather than propagated.
    """
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value
