"""Elevation and local relief, from the USGS 3DEP bare-earth DEM.

Populates two fields:

    elevation_m       mean ground elevation across the tile, metres
    local_relief_m    spread of elevation within the tile, metres

No API key. USGS serves 3DEP free at `elevation.nationalmap.gov`.

## One raster per AOI, not one point per tile

USGS publishes a point service (EPQS) that answers a single coordinate per request.
It works, and it is unusable here: a district is ~1,200 tiles, and when this was
first attempted on 2026-08-20 the service was returning a point every ~28 seconds —
nine hours for one district, assuming none of them failed, which two of five did.

`exportImage` on the 3DEP ImageServer returns the whole AOI as one float32 GeoTIFF
instead. Verified 2026-08-21 over the Phoenix AOI: an 80x60 raster, elevation
327.97-332.94 m. One request per district, ~66 KB.

**That service was down the day before**, returning 504 from both `exportImage` and
EPQS while its metadata endpoint answered normally. The provider therefore treats a
transport failure as misses rather than an exception — a national service being
briefly unwell must not take a diagnosis down with it.

## What "local relief" means here

The elevation *spread within the tile* — max minus min across the DEM cells the tile
covers. Not a neighbourhood window around the tile, which is the other common
reading of the term.

Within-tile is the honest choice for this feature's purpose: it asks whether a tile
is flat or sloped, which is a property of the tile itself. A neighbourhood window
would blend in ground the tile does not contain, and the width of that window would
be an arbitrary parameter nobody could justify.

Downtown Phoenix reads ~5 m of relief across the AOI, which is what a flat desert
city on a river plain should read. Somewhere with real topography would read
differently, and that difference is the signal.
"""

from __future__ import annotations

import io
from typing import Any, Final

import structlog

from .grid import Tile
from .providers import FeatureProvider, ProviderInfo, ProviderResult

log = structlog.get_logger(__name__)

IMAGESERVER_URL: Final[str] = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/"
    "3DEPElevation/ImageServer/exportImage"
)

#: 3DEP's best national coverage is 1/3 arc-second, about 10 m.
DEM_RESOLUTION_M: Final[float] = 10.0

#: Degrees per metre at the equator, for sizing the request.
_DEG_PER_M: Final[float] = 1.0 / 111_320.0

#: Below this, a value is a nodata sentinel rather than ground. 3DEP marks voids
#: with large negatives; the lowest real land on earth is about -430 m.
_MIN_PLAUSIBLE_M: Final[float] = -500.0

#: Above this, likewise. Everest is 8,849 m.
_MAX_PLAUSIBLE_M: Final[float] = 9_000.0

_TIMEOUT_SECONDS: Final[float] = 120.0


class ElevationProvider(FeatureProvider):
    """`elevation_m` and `local_relief_m` from 3DEP."""

    def __init__(self, *, endpoint: str = IMAGESERVER_URL) -> None:
        self._endpoint = endpoint

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="usgs_3dep_elevation",
            resolution_m=DEM_RESOLUTION_M,
            source=(
                "USGS 3DEP bare-earth DEM via elevation.nationalmap.gov "
                "ImageServer exportImage"
            ),
            vintage="3DEP dynamic service",
        )

    @property
    def fields(self) -> tuple[str, ...]:
        return ("elevation_m", "local_relief_m")

    def is_available(self) -> bool:
        try:
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
            dataset, band = self._fetch_dem(west, south, east, north)
        except Exception as exc:  # noqa: BLE001 — never raise on partial coverage
            reason = f"elevation unavailable: {type(exc).__name__}"
            log.warning("terrain.fetch_failed", error=str(exc))
            result.misses = {t.tile_key: reason for t in tiles}
            return result

        answered = 0
        with dataset:
            for tile in tiles:
                values = self._sample(dataset, band, tile)
                if values is None:
                    result.misses[tile.tile_key] = "outside DEM or all void"
                    result.values[tile.tile_key] = {
                        "elevation_m": None, "local_relief_m": None,
                    }
                else:
                    result.values[tile.tile_key] = values
                    answered += 1

        log.info("terrain.parsed", tiles=len(tiles), answered=answered)
        return result

    def _fetch_dem(
        self, west: float, south: float, east: float, north: float
    ) -> tuple[Any, Any]:
        """One exportImage covering the AOI, as float32 GeoTIFF."""
        import httpx
        import rasterio

        cell_deg = DEM_RESOLUTION_M * _DEG_PER_M
        width = max(2, min(4000, int(round((east - west) / cell_deg))))
        height = max(2, min(4000, int(round((north - south) / cell_deg))))

        params = {
            "bbox": f"{west},{south},{east},{north}",
            "bboxSR": "4326",
            "imageSR": "4326",
            "size": f"{width},{height}",
            "format": "tiff",
            # Float, not the default 8-bit render: an integer elevation would
            # quantise away exactly the small relief this feature measures.
            "pixelType": "F32",
            "f": "image",
        }
        response = httpx.get(
            self._endpoint, params=params, timeout=_TIMEOUT_SECONDS
        )
        response.raise_for_status()

        payload = response.content
        # ArcGIS reports errors as JSON or HTML with a 200 as readily as a 4xx.
        if payload[:2] not in (b"II", b"MM"):
            raise ValueError(f"expected a GeoTIFF, got {payload[:120]!r}")

        dataset = rasterio.open(io.BytesIO(payload))
        return dataset, dataset.read(1)

    def _sample(
        self, dataset: Any, band: Any, tile: Tile
    ) -> dict[str, float | None] | None:
        """Mean elevation and within-tile spread over the covered DEM cells."""
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

        import numpy as np

        values = np.asarray(window, dtype="float64").flatten()
        # Voids and sentinels leave before any statistic is taken. A single
        # -3.4e38 in the window would make both the mean and the relief absurd.
        valid = values[
            np.isfinite(values)
            & (values > _MIN_PLAUSIBLE_M)
            & (values < _MAX_PLAUSIBLE_M)
        ]
        if valid.size == 0:
            return None

        return {
            "elevation_m": round(float(valid.mean()), 2),
            "local_relief_m": round(float(valid.max() - valid.min()), 2),
        }
