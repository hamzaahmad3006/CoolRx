"""Land-cover class fractions per tile, from NLCD via WCS.

Populates two fields:

    water_pct         share of the tile that is open water
    grass_shrub_pct   share that is grassland, herbaceous or shrub/scrub

## Why WCS and not WMS

`geo/mrlc.py` reads the impervious and canopy layers over **WMS**, because those are
continuous 0-100 percentage rasters and a rendered image carries the same numbers.
The land-cover layer is different: it is *categorical*, and WMS returns the rendered
**palette index** rather than the class code. Verified on the Phoenix AOI — the WMS
GeoTIFF held {4, 5, 6} where NLCD classes are 11/21/…/95, while `GetFeatureInfo` on
the same pixel reported 24.

WCS returns the real values. Two details make it work, both found the hard way:

1. The coverage is published in **EPSG:3857**, not Albers 5070. Subsetting with
   Albers coordinates returns "Empty intersection after subsetting", because the
   numbers fall outside the declared envelope.
2. GeoServer cannot write GeoTIFF in 3857 — it fails with *"Unable to map projection
   Popular Visualisation Pseudo Mercator"*. Passing `outputCrs=EPSG:4326` reprojects
   the output and succeeds.

So: subset in Web Mercator, ask for WGS84 out. The same Phoenix box then returns
{22: 4, 23: 181, 24: 595} — Developed Low, Medium and High Intensity, which is what
a downtown core is, and consistent with the 85% impervious and ~0% canopy the other
two providers read for the same tiles.

## Why `albedo_proxy` is not here

The third feature the class layer could supply needs a reflectance value per land
cover class. Those exist in the literature, but assigning numbers without a citation
is the same P1 violation as inventing a catalog cost — and albedo feeds a predicted
temperature reduction a city would spend money on. It stays null until the values
come from a source that can be printed in the report.
"""

from __future__ import annotations

import io
from typing import Any, Final

import structlog

from . import _http
from .grid import Tile
from .providers import FeatureProvider, ProviderInfo, ProviderResult

log = structlog.get_logger(__name__)

WCS_ENDPOINT: Final[str] = "https://www.mrlc.gov/geoserver/mrlc_display/wcs"

#: NLCD's native cell size.
NLCD_RESOLUTION_M: Final[float] = 30.0

#: Open Water. Class 12 (perennial ice/snow) is deliberately excluded — it is not
#: water in any sense that cools a street.
_WATER_CLASSES: Final[frozenset[int]] = frozenset({11})

#: Shrub/Scrub and Grassland/Herbaceous. Pasture (81) and Cultivated Crops (82) are
#: excluded: they are agricultural cover, and the feature name says grass and shrub.
_GRASS_SHRUB_CLASSES: Final[frozenset[int]] = frozenset({52, 71})

#: Every value NLCD legitimately uses. Anything else in the raster is fill or a
#: rendering artefact, and is excluded from the denominator rather than counted as
#: "not water" — which would quietly inflate every fraction.
_VALID_CLASSES: Final[frozenset[int]] = frozenset(
    {11, 12, 21, 22, 23, 24, 31, 41, 42, 43, 52, 71, 81, 82, 90, 95}
)

_TIMEOUT_SECONDS: Final[float] = 120.0


class LandCoverProvider(FeatureProvider):
    """`water_pct` and `grass_shrub_pct` from NLCD land-cover classes."""

    def __init__(
        self,
        *,
        year: int = 2021,
        endpoint: str = WCS_ENDPOINT,
    ) -> None:
        self._year = year
        self._endpoint = endpoint
        self._coverage = f"mrlc_display__NLCD_{year}_Land_Cover_L48"

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="nlcd_land_cover",
            resolution_m=NLCD_RESOLUTION_M,
            source=(
                f"NLCD {self._year} Land Cover (CONUS), USGS/MRLC, "
                "served via mrlc.gov WCS"
            ),
            vintage=str(self._year),
        )

    @property
    def fields(self) -> tuple[str, ...]:
        return ("water_pct", "grass_shrub_pct")

    def is_available(self) -> bool:
        try:
            import pyproj  # noqa: F401
            import rasterio  # noqa: F401
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
            dataset, band = self._fetch_coverage(west, south, east, north)
        except Exception as exc:  # noqa: BLE001 — never raise on partial coverage
            reason = f"land cover unavailable: {type(exc).__name__}"
            log.warning("landcover.fetch_failed", error=str(exc))
            result.misses = {t.tile_key: reason for t in tiles}
            return result

        answered = 0
        with dataset:
            for tile in tiles:
                fractions = self._fractions(dataset, band, tile)
                if fractions is None:
                    result.misses[tile.tile_key] = "outside coverage or no valid class"
                    result.values[tile.tile_key] = {
                        "water_pct": None, "grass_shrub_pct": None,
                    }
                else:
                    result.values[tile.tile_key] = fractions
                    answered += 1

        log.info("landcover.parsed", tiles=len(tiles), answered=answered)
        return result

    def _fetch_coverage(
        self, west: float, south: float, east: float, north: float
    ) -> tuple[Any, Any]:
        """One WCS GetCoverage for the whole AOI.

        Subset in the coverage's own EPSG:3857, output in 4326 — see the module
        docstring for why neither half is optional.
        """
        import httpx
        import rasterio
        from pyproj import Transformer

        to_mercator = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
        x1, y1 = to_mercator.transform(west, south)
        x2, y2 = to_mercator.transform(east, north)

        params = {
            "service": "WCS",
            "version": "2.0.1",
            "request": "GetCoverage",
            "coverageId": self._coverage,
            "format": "image/geotiff",
            "outputCrs": "http://www.opengis.net/def/crs/EPSG/0/4326",
            "subset": [
                f"X({min(x1, x2):.1f},{max(x1, x2):.1f})",
                f"Y({min(y1, y2):.1f},{max(y1, y2):.1f})",
            ],
        }
        response = _http.get(
            self._endpoint, params=params, timeout=_TIMEOUT_SECONDS
        )
        response.raise_for_status()

        payload = response.content
        # WCS reports failure as an XML ExceptionReport, sometimes with a 200.
        if payload[:2] not in (b"II", b"MM"):
            raise ValueError(f"expected a GeoTIFF, got {payload[:120]!r}")

        dataset = rasterio.open(io.BytesIO(payload))
        return dataset, dataset.read(1)

    def _fractions(
        self, dataset: Any, band: Any, tile: Tile
    ) -> dict[str, float | None] | None:
        """Class fractions over the cells a tile covers.

        The denominator is *valid* cells only. Counting fill values as "not water"
        would make every fraction quietly too small.
        """
        try:
            row_hi, col_lo = dataset.index(tile.west, tile.north)
            row_lo, col_hi = dataset.index(tile.east, tile.south)
        except Exception:  # noqa: BLE001 — outside the transform
            return None

        row_start, row_stop = sorted((row_hi, row_lo))
        col_start, col_stop = sorted((col_lo, col_hi))
        row_start = max(0, row_start)
        col_start = max(0, col_start)
        row_stop = min(band.shape[0] - 1, row_stop)
        col_stop = min(band.shape[1] - 1, col_stop)
        if row_start > row_stop or col_start > col_stop:
            return None

        window = band[row_start : row_stop + 1, col_start : col_stop + 1]
        if window.size == 0:
            return None

        total = 0
        water = 0
        grass_shrub = 0
        for value in window.flatten().tolist():
            klass = int(value)
            if klass not in _VALID_CLASSES:
                continue
            total += 1
            if klass in _WATER_CLASSES:
                water += 1
            elif klass in _GRASS_SHRUB_CLASSES:
                grass_shrub += 1

        if total == 0:
            return None

        return {
            "water_pct": round(100.0 * water / total, 2),
            "grass_shrub_pct": round(100.0 * grass_shrub / total, 2),
        }
