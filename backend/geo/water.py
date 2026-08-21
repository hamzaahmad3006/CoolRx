"""Distance from each tile to the nearest open water.

Populates one field:

    dist_to_water_m    straight-line distance to the nearest NLCD open-water cell

No API key. Water comes from the same NLCD land-cover coverage `geo/landcover.py`
reads over WCS, so the two features cannot disagree about where water is.

## The search window, and why the answer is sometimes null

Water that cools a district is frequently outside the district. Fetching land cover
only over the AOI would report "no water" for anywhere whose river sits a kilometre
beyond the study boundary, so the coverage is fetched over the AOI **expanded by a
buffer** (default 10 km) and the distance transform runs across that whole window.

If no open water appears anywhere in the buffered window, the field is **null, not a
large number**. A tile 10 km from water and one 60 km from it would both need a
figure this method cannot produce, and inventing a floor value would put a fabricated
distance into a feature the model trains on. The miss records the radius searched, so
"null" is readable as "no water within 10 km" rather than as an unexplained gap.

## Distance is measured on the ground, not in degrees

The transform runs in pixels, then converts using metres-per-pixel computed at the
window's own latitude — a degree of longitude is ~93 km at Phoenix's latitude, not
111 km, and using the equatorial figure would overstate every east-west distance by
about 20%.

Diagonal distance is Euclidean rather than city-block, because heat does not travel
along streets.
"""

from __future__ import annotations

import math
from typing import Any, Final

import structlog

from .grid import Tile
from .landcover import LandCoverProvider
from .providers import FeatureProvider, ProviderInfo, ProviderResult

log = structlog.get_logger(__name__)

#: NLCD Open Water. Ice and snow (12) is excluded for the same reason as in
#: landcover.py: it is not water that cools a street.
_WATER_CLASS: Final[int] = 11

#: How far beyond the AOI to look. Large enough that a river or lake serving the
#: district is usually inside it; small enough that the raster stays modest.
DEFAULT_SEARCH_BUFFER_M: Final[float] = 10_000.0

_DEG_PER_M_LAT: Final[float] = 1.0 / 111_320.0

NLCD_RESOLUTION_M: Final[float] = 30.0


class WaterDistanceProvider(FeatureProvider):
    """`dist_to_water_m` by distance transform over NLCD open water."""

    def __init__(
        self,
        *,
        year: int = 2021,
        search_buffer_m: float = DEFAULT_SEARCH_BUFFER_M,
    ) -> None:
        self._year = year
        self._buffer_m = search_buffer_m
        self._land_cover = LandCoverProvider(year=year)

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="nlcd_water_distance",
            resolution_m=NLCD_RESOLUTION_M,
            source=(
                f"Distance to NLCD {self._year} open water (class 11), USGS/MRLC "
                f"via WCS; searched within {int(self._buffer_m / 1000)} km of the AOI"
            ),
            vintage=str(self._year),
        )

    @property
    def fields(self) -> tuple[str, ...]:
        return ("dist_to_water_m",)

    def is_available(self) -> bool:
        try:
            import rasterio  # noqa: F401
            import scipy.ndimage  # noqa: F401
        except ImportError:
            return False
        return self._land_cover.is_available()

    # ── the work ─────────────────────────────────────────────────────────────

    def fetch(self, tiles: list[Tile]) -> ProviderResult:
        result = ProviderResult(info=self.info)
        if not tiles:
            return result

        west = min(t.west for t in tiles)
        south = min(t.south for t in tiles)
        east = max(t.east for t in tiles)
        north = max(t.north for t in tiles)

        mid_lat = (south + north) / 2.0
        pad_lat = self._buffer_m * _DEG_PER_M_LAT
        # A degree of longitude shortens with latitude; without this the buffer
        # would be narrower east-west than intended.
        pad_lon = pad_lat / max(0.1, math.cos(math.radians(mid_lat)))

        try:
            dataset, band = self._land_cover._fetch_coverage(
                west - pad_lon, south - pad_lat, east + pad_lon, north + pad_lat
            )
        except Exception as exc:  # noqa: BLE001 — never raise on partial coverage
            reason = f"water distance unavailable: {type(exc).__name__}"
            log.warning("water.fetch_failed", error=str(exc))
            result.misses = {t.tile_key: reason for t in tiles}
            return result

        with dataset:
            distances = self._distance_metres(dataset, band, mid_lat)
            if distances is None:
                reason = (
                    f"no open water within {int(self._buffer_m / 1000)} km of the AOI"
                )
                for tile in tiles:
                    result.misses[tile.tile_key] = reason
                    result.values[tile.tile_key] = {"dist_to_water_m": None}
                log.info("water.no_water_in_window", tiles=len(tiles))
                return result

            answered = 0
            for tile in tiles:
                value = self._sample(dataset, distances, tile)
                if value is None:
                    result.misses[tile.tile_key] = "outside the searched window"
                    result.values[tile.tile_key] = {"dist_to_water_m": None}
                else:
                    result.values[tile.tile_key] = {"dist_to_water_m": value}
                    answered += 1

        log.info("water.parsed", tiles=len(tiles), answered=answered)
        return result

    def _distance_metres(
        self, dataset: Any, band: Any, mid_lat: float
    ) -> Any | None:
        """Per-cell distance to the nearest water cell, in metres.

        Returns None when the window holds no water at all — the caller turns
        that into nulls rather than a floor value.
        """
        import numpy as np
        from scipy.ndimage import distance_transform_edt

        water = np.asarray(band) == _WATER_CLASS
        if not water.any():
            return None

        # Ground size of one pixel. Latitude and longitude degrees differ, so the
        # transform is given both and returns true metres rather than pixels.
        transform = dataset.transform
        metres_per_px_y = abs(transform.e) / _DEG_PER_M_LAT
        metres_per_px_x = (
            abs(transform.a) / _DEG_PER_M_LAT * math.cos(math.radians(mid_lat))
        )

        return distance_transform_edt(
            ~water, sampling=(metres_per_px_y, metres_per_px_x)
        )

    def _sample(self, dataset: Any, distances: Any, tile: Tile) -> float | None:
        """Distance at the tile's centroid.

        The centroid rather than the window mean: distance to water is a smooth
        field, and averaging it across a tile's cells would bias every tile
        slightly away from the water it is nearest to.
        """
        try:
            row, col = dataset.index(tile.centroid_lon, tile.centroid_lat)
        except Exception:  # noqa: BLE001
            return None

        if not (0 <= row < distances.shape[0] and 0 <= col < distances.shape[1]):
            return None

        return round(float(distances[row, col]), 1)
