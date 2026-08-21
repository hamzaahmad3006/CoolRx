"""Poverty rate per tile, at census-tract resolution.

Populates one field on `exposure`:

    pct_poverty    share of the population below the poverty line

## Why this is a separate provider from `census.py`

ACS does not publish `B17001` below **tract** level — verified 2026-08-19, the
block-group query returns `null` for every row while the tract query returns real
figures. `CensusExposureProvider` declares block-group resolution, and serving a
tract number through it would overstate how precise it is. The SRS makes the same
point about SVI: a coarser input must be labelled at its true resolution rather than
implied to be tile-level.

So this provider exists to carry a different, honestly-declared resolution. Tracts in
the Phoenix AOI run to several thousand residents each — far coarser than a 60-100 m
tile — and `ProviderInfo.resolution_m` says so.

## A rate is not a count

`census.py` *apportions* population: a tile covering 30% of a block group receives
30% of its people, and the totals conserve. A rate cannot be treated that way. 37.6%
poverty over a tract does not become 11.3% because a tile covers 30% of it — the
tile's residents are still drawn from a population where 37.6% are below the line.

So the rate is **assigned**, not divided. Where a tile straddles two tracts the rate
is weighted by overlap area, which mixes the two rates rather than diluting either.

## Boundaries come from the block-group layer

A tract GEOID is the first 11 characters of a block-group GEOID, so the same
TIGERweb query `census.py` already uses gives the tracts for free. One less endpoint
to depend on, and one less thing to break.

## SVI is not here

`svi_score` and `svi_source_geoid` stay null. CDC/ATSDR publishes SVI at tract level,
which would fit this provider exactly, but as of 2026-08-20 the dataset on
data.cdc.gov (`ypqf-r5qs`) is registered as a **map asset with zero queryable
columns** — the Socrata row endpoint returns `[{}]` — and the other catalogue ids
return 404. Guessing at a download URL would risk silently loading the wrong
vintage or the wrong geography under an equity weighting a city would act on, so
the field is left null until the real source is confirmed.
"""

from __future__ import annotations

from typing import Any, Final

import structlog

from . import _http
from .grid import Tile
from .providers import FeatureProvider, ProviderInfo, ProviderResult

log = structlog.get_logger(__name__)

ACS_URL: Final[str] = "https://api.census.gov/data/{year}/acs/acs5"

#: Population for whom poverty status is determined — the denominator. It is not
#: the tract's total population; institutionalised residents are excluded, so
#: dividing by B01003 would understate the rate.
_POVERTY_UNIVERSE: Final[str] = "B17001_001E"

#: Income in the past 12 months below the poverty level.
_BELOW_POVERTY: Final[str] = "B17001_002E"

_TIMEOUT_SECONDS: Final[float] = 90.0

#: Length of a census tract GEOID: state(2) + county(3) + tract(6).
_TRACT_GEOID_LENGTH: Final[int] = 11


class PovertyProvider(FeatureProvider):
    """Tract-level poverty rate, assigned to tiles by overlap."""

    def __init__(self, *, api_key: str | None, year: int = 2023) -> None:
        self._api_key = (api_key or "").strip()
        self._year = year

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="census_acs_poverty",
            # Tracts vary in size and are far coarser than a tile. None rather
            # than a number, for the same reason census.py declares None: any
            # single figure would imply a precision the source does not have.
            resolution_m=None,
            source=(
                f"US Census ACS {self._year} 5-year, table B17001 at CENSUS TRACT "
                "resolution (coarser than a tile), boundaries from TIGERweb"
            ),
            vintage=f"ACS {self._year} 5-year",
        )

    @property
    def fields(self) -> tuple[str, ...]:
        return ("pct_poverty",)

    def is_available(self) -> bool:
        if not self._api_key:
            log.info("poverty.unavailable", reason="CENSUS_API_KEY is not set")
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
            reason = "poverty unavailable: CENSUS_API_KEY not set"
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
            rates = self._poverty_rates(groups)
            if not rates:
                raise ValueError("ACS returned no usable poverty figures")
        except Exception as exc:  # noqa: BLE001 — never raise on partial coverage
            reason = f"poverty unavailable: {type(exc).__name__}"
            log.warning("poverty.fetch_failed", error=str(exc))
            result.misses = {t.tile_key: reason for t in tiles}
            return result

        self._assign(tiles, groups, rates, result)
        return result

    def _block_groups(
        self, west: float, south: float, east: float, north: float
    ) -> list[dict[str, Any]]:
        """Reuses the census boundary query; a tract GEOID is a GEOID prefix."""
        from .census import CensusExposureProvider

        return CensusExposureProvider(
            api_key=self._api_key, year=self._year
        )._block_groups(west, south, east, north)

    def _poverty_rates(self, groups: list[dict[str, Any]]) -> dict[str, float]:
        """Tract GEOID → poverty rate, one ACS request per tract."""
        import httpx

        tracts: set[tuple[str, str, str]] = set()
        for feature in groups:
            p = feature.get("properties") or {}
            if p.get("STATE") and p.get("COUNTY") and p.get("TRACT"):
                tracts.add((p["STATE"], p["COUNTY"], p["TRACT"]))

        variables = f"{_POVERTY_UNIVERSE},{_BELOW_POVERTY}"
        rates: dict[str, float] = {}

        for state, county, tract in sorted(tracts):
            params = {
                "get": variables,
                "for": f"tract:{tract}",
                "in": f"state:{state} county:{county}",
                "key": self._api_key,
            }
            response = _http.get(
                ACS_URL.format(year=self._year),
                params=params,
                timeout=_TIMEOUT_SECONDS,
            )
            if response.status_code == 204:
                continue
            response.raise_for_status()

            header, *body = response.json()
            index = {name: i for i, name in enumerate(header)}
            for row in body:
                universe = _number(row[index[_POVERTY_UNIVERSE]])
                below = _number(row[index[_BELOW_POVERTY]])
                if not universe or below is None:
                    # A universe of zero is not a poverty rate of zero; it means
                    # nobody there had poverty status determined.
                    continue
                rates[state + county + tract] = round(below / universe, 4)

        return rates

    def _assign(
        self,
        tiles: list[Tile],
        groups: list[dict[str, Any]],
        rates: dict[str, float],
        result: ProviderResult,
    ) -> None:
        from shapely.geometry import box, shape

        prepared: list[tuple[Any, float]] = []
        for feature in groups:
            geoid = str((feature.get("properties") or {}).get("GEOID") or "")
            rate = rates.get(geoid[:_TRACT_GEOID_LENGTH])
            if rate is None:
                continue
            try:
                geometry = shape(feature["geometry"])
            except Exception:  # noqa: BLE001
                continue
            if geometry.is_empty:
                continue
            prepared.append((geometry, rate))

        answered = 0
        for tile in tiles:
            cell = box(tile.west, tile.south, tile.east, tile.north)
            weighted = 0.0
            covered = 0.0

            for geometry, rate in prepared:
                if not cell.intersects(geometry):
                    continue
                overlap = cell.intersection(geometry).area
                if overlap <= 0:
                    continue
                # Area-weighted so a tile spanning two tracts gets a mix of their
                # rates. Never divided by coverage share — a rate is not a count.
                weighted += rate * overlap
                covered += overlap

            if covered <= 0:
                result.misses[tile.tile_key] = "tile intersects no tract with a rate"
                result.values[tile.tile_key] = {"pct_poverty": None}
                continue

            result.values[tile.tile_key] = {
                "pct_poverty": round(weighted / covered, 4)
            }
            answered += 1

        log.info("poverty.assigned", tiles=len(tiles), answered=answered)


def _number(raw: Any) -> float | None:
    """ACS sends strings, `null` where unpublished, and negative annotation codes."""
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value
