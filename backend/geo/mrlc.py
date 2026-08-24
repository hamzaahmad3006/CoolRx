"""NLCD land-cover providers, served from MRLC's public WMS.

Two features are populated here, both as true percentages read straight from the
source raster:

    impervious_pct   NLCD Impervious Surface     0-100
    canopy_pct       NLCD/USFS Tree Canopy Cover 0-100

No API key. MRLC serves these free at <https://www.mrlc.gov/geoserver>.

## Why one raster per AOI instead of one query per tile

The obvious implementation is a `GetFeatureInfo` point query per tile. A district is
~1,200 tiles and each feature needs its own layer, so that is ~2,400 requests against
a free public service for one diagnosis — rude, slow, and rate-limit bait.

Instead each layer is fetched **once per AOI** as a GeoTIFF via `GetMap`, sized to
NLCD's native 30 m grid, and every tile is then sampled locally. Two requests per
district, and the raster is small: the Phoenix AOI comes back at ~2.5 KB.

## Why percentage layers and not the land-cover class layer

`NLCD_2021_Land_Cover_L48` would give `water_pct`, `grass_shrub_pct` and an albedo
proxy — but over WMS it returns **rendered palette indices, not class codes**.
Verified 2026-08-19 on the Phoenix AOI: the raster came back holding {4, 5, 6} where
NLCD classes are 11/21/22/23/24/41/52/71/…. `GetFeatureInfo` on the same pixel
reported 24 (Developed, High Intensity), so the palette index is not the class value
and the mapping between them is undocumented.

Guessing that mapping would put invented land-cover under every downstream figure,
which is the same P1 violation as inventing a catalog cost. So those three features
stay null and are reported as unavailable until the class values can be read
properly — WCS is the likely route, but its axis subsetting rejected both the
geographic and the Albers envelope on first attempt and needs its own investigation.

The impervious and canopy layers have no such problem: they are continuous 0-100
percentage rasters, and what is read is what the pixel holds.

## Confidence in the values

Cross-checked on the same downtown Phoenix pixel, three independent layers agree:
land cover reports class 24 (Developed, High Intensity), impervious reads a mean of
85.2%, canopy reads ~0%. A dense urban core is exactly what that combination
describes.
"""

from __future__ import annotations

import io
from typing import Any, Final

import structlog

from . import _http
from .grid import Tile
from .providers import FeatureProvider, ProviderInfo, ProviderResult

log = structlog.get_logger(__name__)

WMS_ENDPOINT: Final[str] = "https://www.mrlc.gov/geoserver/mrlc_display/wms"

#: NLCD's native cell size. The request is sized to this so the server resamples
#: as little as possible; asking for a finer grid would invent detail.
NLCD_RESOLUTION_M: Final[float] = 30.0

#: Degrees per metre at the equator, for sizing the request. Latitude shrinks the
#: longitude degree, which only ever makes the request *finer* than 30 m — safe.
_DEG_PER_M: Final[float] = 1.0 / 111_320.0

#: A percentage layer cannot exceed this. Anything above is a fill/nodata marker
#: (NLCD uses 250-255), not a measurement, and is discarded rather than clamped.
_MAX_VALID_PERCENT: Final[float] = 100.0

_TIMEOUT_SECONDS: Final[float] = 90.0


class _MrlcPercentLayer(FeatureProvider):
    """Shared behaviour for the two continuous 0-100 NLCD layers."""

    def __init__(
        self,
        *,
        name: str,
        layer: str,
        field_name: str,
        source: str,
        vintage: str,
        endpoint: str = WMS_ENDPOINT,
    ) -> None:
        self._name = name
        self._layer = layer
        self._field = field_name
        self._source = source
        self._vintage = vintage
        self._endpoint = endpoint

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name=self._name,
            resolution_m=NLCD_RESOLUTION_M,
            source=self._source,
            vintage=self._vintage,
        )

    @property
    def fields(self) -> tuple[str, ...]:
        return (self._field,)

    def is_available(self) -> bool:
        """Whether the dependencies for reading a raster are importable.

        Network reachability is deliberately *not* probed here: a readiness check
        that makes a live call turns every startup into a request against someone
        else's free service. A network failure surfaces as misses in `fetch`.
        """
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
            raster = self._fetch_raster(west, south, east, north)
        except Exception as exc:  # noqa: BLE001 — never raise on partial coverage
            reason = f"{self._name} unavailable: {type(exc).__name__}"
            log.warning(
                "mrlc.fetch_failed",
                provider=self._name,
                layer=self._layer,
                error=str(exc),
            )
            result.misses = {t.tile_key: reason for t in tiles}
            return result

        dataset, band = raster
        answered = 0
        with dataset:
            for tile in tiles:
                value = self._sample(dataset, band, tile)
                if value is None:
                    result.misses[tile.tile_key] = "outside raster or no-data"
                    result.values[tile.tile_key] = {self._field: None}
                else:
                    result.values[tile.tile_key] = {self._field: value}
                    answered += 1

        log.info(
            "mrlc.parsed",
            provider=self._name,
            tiles=len(tiles),
            answered=answered,
        )
        return result

    def _fetch_raster(
        self, west: float, south: float, east: float, north: float
    ) -> tuple[Any, Any]:
        """One GetMap for the whole AOI, read into memory as a GeoTIFF."""
        import rasterio

        # Size the request to NLCD's own grid. At least 2 px each way so a tiny
        # AOI still produces a readable raster.
        cell_deg = NLCD_RESOLUTION_M * _DEG_PER_M
        width = max(2, int(round((east - west) / cell_deg)))
        height = max(2, int(round((north - south) / cell_deg)))

        params = {
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetMap",
            "layers": self._layer,
            "srs": "EPSG:4326",
            "bbox": f"{west},{south},{east},{north}",
            "width": str(width),
            "height": str(height),
            "format": "image/geotiff",
        }
        response = _http.get(
            self._endpoint, params=params, timeout=_TIMEOUT_SECONDS
        )
        response.raise_for_status()

        payload = response.content
        # A WMS error comes back as XML with a 200, so the magic bytes are what
        # actually distinguishes a raster from a ServiceExceptionReport.
        if payload[:2] not in (b"II", b"MM"):
            raise ValueError(
                f"expected a GeoTIFF, got {payload[:80]!r}"
            )

        dataset = rasterio.open(io.BytesIO(payload))
        return dataset, dataset.read(1)

    def _sample(self, dataset: Any, band: Any, tile: Tile) -> float | None:
        """Mean of the raster cells falling inside one tile.

        The mean, not the centroid value: a 60-100 m tile spans several 30 m NLCD
        cells, and "percent impervious across this tile" is what the feature means.
        Falls back to the centroid cell when the tile is smaller than one cell.
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

        # Drop fill/nodata before averaging. Averaging 255 into a percentage
        # would silently invent an impossible value.
        valid = window[window <= _MAX_VALID_PERCENT]
        if valid.size == 0:
            return None

        return round(float(valid.mean()), 2)


def fetch_percent_raster(
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    layer: str = "NLCD_2021_Impervious_L48",
    endpoint: str = WMS_ENDPOINT,
) -> tuple[Any, Any]:
    """One NLCD percentage layer over an arbitrary box, as (dataset, band).

    Exposed separately from the providers because the census dasymetric weighting
    needs impervious cover over whole *block groups*, which extend well past the
    study area — measured at 2.2x wider and 2.5x taller than the Phoenix AOI. A
    weight surface clipped to the AOI would normalise each block group's
    population over only the part inside it, and hand the study area every
    resident of a group that mostly lies outside it.
    """
    layer_reader = _MrlcPercentLayer(
        name="weight_surface",
        layer=layer,
        field_name="weight",
        source="NLCD Impervious Surface, USGS/MRLC",
        vintage="2021",
        endpoint=endpoint,
    )
    return layer_reader._fetch_raster(west, south, east, north)


class ImperviousProvider(_MrlcPercentLayer):
    """`impervious_pct` from NLCD Impervious Surface."""

    def __init__(self, *, year: int = 2021, endpoint: str = WMS_ENDPOINT) -> None:
        super().__init__(
            name="nlcd_impervious",
            layer=f"NLCD_{year}_Impervious_L48",
            field_name="impervious_pct",
            source=(
                f"NLCD {year} Impervious Surface (CONUS), USGS/MRLC, "
                "served via mrlc.gov WMS"
            ),
            vintage=str(year),
            endpoint=endpoint,
        )


class TreeCanopyProvider(_MrlcPercentLayer):
    """`canopy_pct` from the NLCD/USFS Tree Canopy Cover product."""

    def __init__(self, *, year: int = 2021, endpoint: str = WMS_ENDPOINT) -> None:
        super().__init__(
            name="nlcd_tree_canopy",
            layer=f"nlcd_tcc_conus_{year}_v2021-4",
            field_name="canopy_pct",
            source=(
                f"NLCD Tree Canopy Cover {year} (CONUS, v2021-4), USFS/MRLC, "
                "served via mrlc.gov WMS"
            ),
            vintage=f"{year} (v2021-4)",
            endpoint=endpoint,
        )
