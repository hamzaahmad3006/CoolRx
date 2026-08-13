"""Geospatial layer — tiling and per-tile feature enrichment.

Pure geometry and data plumbing. Nothing here calls FortyGuard, touches the
database, or knows what a plan is; it turns a bounding box into tiles and tiles
into feature rows.

Raster and network providers are imported lazily by `default_providers` so the
grid can be built — and tested — without rasterio, GDAL or a network.
"""

from __future__ import annotations

import structlog

from .enrich import (
    EnrichmentReport,
    FieldCoverage,
    apply_district_mean,
    enrich_tiles,
)
from .grid import (
    MAX_TILES,
    VALID_GRANULARITIES,
    GridSpec,
    Tile,
    build_grid,
    estimate_tile_count,
    utm_epsg_for,
)
from .providers import (
    REQUIRED_FEATURE_FIELDS,
    FeatureProvider,
    GeometryProvider,
    ProviderInfo,
    ProviderResult,
    UnavailableProvider,
)
from .tilekey import decode_geohash, encode_geohash, tile_key

log = structlog.get_logger(__name__)

__all__ = [
    "MAX_TILES",
    "REQUIRED_FEATURE_FIELDS",
    "VALID_GRANULARITIES",
    "EnrichmentReport",
    "FeatureProvider",
    "FieldCoverage",
    "GeometryProvider",
    "GridSpec",
    "ProviderInfo",
    "ProviderResult",
    "Tile",
    "UnavailableProvider",
    "apply_district_mean",
    "build_grid",
    "decode_geohash",
    "default_providers",
    "encode_geohash",
    "enrich_tiles",
    "estimate_tile_count",
    "tile_key",
    "utm_epsg_for",
]


def default_providers(
    *, hour_utc: int | None = None, doy: int | None = None
) -> list[FeatureProvider]:
    """The provider chain for a normal enrichment run.

    Every optional provider is imported inside a try/except and replaced with an
    `UnavailableProvider` when its dependency or data is missing. The run then
    completes with an explicitly-null column and a named reason, rather than
    crashing — or, worse, quietly omitting the field so downstream code defaults it.
    """
    providers: list[FeatureProvider] = [
        GeometryProvider(hour_utc=hour_utc, doy=doy)
    ]

    try:
        from .landcover import NlcdProvider

        providers.append(NlcdProvider())
    except Exception as exc:  # noqa: BLE001 — availability, not correctness
        log.info("providers.landcover_unavailable", detail=str(exc))
        providers.append(
            UnavailableProvider(
                name="nlcd",
                fields=(
                    "canopy_pct",
                    "impervious_pct",
                    "building_pct",
                    "water_pct",
                    "grass_shrub_pct",
                    "albedo_proxy",
                ),
                reason=f"NLCD provider unavailable: {exc}",
            )
        )

    try:
        from .terrain import TerrainProvider

        providers.append(TerrainProvider())
    except Exception as exc:  # noqa: BLE001
        log.info("providers.terrain_unavailable", detail=str(exc))
        providers.append(
            UnavailableProvider(
                name="terrain",
                fields=("elevation_m", "local_relief_m", "dist_to_water_m"),
                reason=f"Terrain provider unavailable: {exc}",
            )
        )

    return providers
