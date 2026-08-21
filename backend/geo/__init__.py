"""Geospatial layer — tiling and per-tile feature enrichment.

Pure geometry and data plumbing. Nothing here calls FortyGuard, touches the
database, or knows what a plan is; it turns a bounding box into tiles and tiles
into feature rows.

Raster and network providers are imported lazily by `default_providers` so the
grid can be built — and tested — without rasterio, GDAL or a network.
"""

from __future__ import annotations

from collections.abc import Callable

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
    ENRICHABLE_FIELDS,
    EXPOSURE_FIELDS,
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
    "ENRICHABLE_FIELDS",
    "EXPOSURE_FIELDS",
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


def _register(
    providers: list[FeatureProvider],
    *,
    name: str,
    fields: tuple[str, ...],
    build: Callable[[], FeatureProvider],
) -> None:
    """Append a provider, or an `UnavailableProvider` standing in its place.

    Two ways a provider can fail to arrive, both handled the same way:

    * it raises on construction — a missing dependency, a bad argument, or an
      `ImportError` because the class was renamed;
    * it constructs but reports `is_available()` False — rasterio absent, no API
      key.

    Either way the run continues with an explicitly-null column and a named
    reason, rather than crashing or quietly omitting the field.
    """
    try:
        provider = build()
        if not provider.is_available():
            raise RuntimeError("provider reports itself unavailable")
    except Exception as exc:  # noqa: BLE001 — availability, not correctness
        log.info(f"providers.{name}_unavailable", detail=str(exc))
        providers.append(
            UnavailableProvider(
                name=name, fields=fields, reason=f"{name} unavailable: {exc}"
            )
        )
        return

    providers.append(provider)


def default_providers(
    *,
    hour_utc: int | None = None,
    doy: int | None = None,
    census_api_key: str | None = None,
) -> list[FeatureProvider]:
    """The provider chain for a normal enrichment run.

    Ordered: `enrich_tiles` lets the first provider that answers for a field win.

    Every provider is registered through `_register`, which substitutes an
    `UnavailableProvider` when the real one cannot be built. That degradation is
    deliberate — a national raster service being briefly unwell must not take a
    diagnosis down with it — but it is also silent, and on 2026-08-21 it hid a
    real defect for a week: this factory imported `NlcdProvider` and
    `TerrainProvider`, names that never existed, so every land-cover and terrain
    feature was null in every run while the tests stayed green.

    `test_default_providers.py` now asserts that nothing in this chain degrades
    when its dependencies are present, so a rename cannot fail silently again.

    `albedo_proxy` and `openness_proxy` are registered as explicitly unavailable.
    They are in `REQUIRED_FEATURE_FIELDS` but have no honest source yet — albedo
    needs a citable per-class reflectance table, openness needs building heights.
    Naming them here keeps them visible as null-with-a-reason rather than absent.
    """
    providers: list[FeatureProvider] = [
        GeometryProvider(hour_utc=hour_utc, doy=doy)
    ]

    # ── land cover ───────────────────────────────────────────────────────────
    def _impervious() -> FeatureProvider:
        from .mrlc import ImperviousProvider

        return ImperviousProvider()

    def _canopy() -> FeatureProvider:
        from .mrlc import TreeCanopyProvider

        return TreeCanopyProvider()

    def _landcover() -> FeatureProvider:
        from .landcover import LandCoverProvider

        return LandCoverProvider()

    def _buildings() -> FeatureProvider:
        from .buildings import BuildingFootprintProvider

        return BuildingFootprintProvider()

    _register(
        providers, name="nlcd_impervious", fields=("impervious_pct",),
        build=_impervious,
    )
    _register(
        providers, name="nlcd_tree_canopy", fields=("canopy_pct",), build=_canopy,
    )
    _register(
        providers, name="nlcd_land_cover",
        fields=("water_pct", "grass_shrub_pct"), build=_landcover,
    )
    _register(
        providers, name="osm_building_footprints", fields=("building_pct",),
        build=_buildings,
    )

    # ── terrain ──────────────────────────────────────────────────────────────
    def _elevation() -> FeatureProvider:
        from .terrain import ElevationProvider

        return ElevationProvider()

    def _water() -> FeatureProvider:
        from .water import WaterDistanceProvider

        return WaterDistanceProvider()

    _register(
        providers, name="usgs_3dep_elevation",
        fields=("elevation_m", "local_relief_m"), build=_elevation,
    )
    _register(
        providers, name="nhd_water_distance", fields=("dist_to_water_m",),
        build=_water,
    )

    # ── population and equity ────────────────────────────────────────────────
    # Not in REQUIRED_FEATURE_FIELDS — the model does not train on them — but the
    # exposure and equity views cannot be computed without them.
    def _census() -> FeatureProvider:
        from .census import CensusExposureProvider

        return CensusExposureProvider(api_key=census_api_key)

    def _poverty() -> FeatureProvider:
        from .poverty import PovertyProvider

        return PovertyProvider(api_key=census_api_key)

    _register(
        providers, name="census_acs_exposure", fields=("population", "pct_over65"),
        build=_census,
    )
    _register(
        providers, name="census_acs_poverty", fields=("pct_poverty",), build=_poverty,
    )

    # ── required, but not yet sourceable ─────────────────────────────────────
    providers.append(
        UnavailableProvider(
            name="albedo_proxy",
            fields=("albedo_proxy",),
            reason=(
                "no citable per-class reflectance table yet; albedo feeds a "
                "predicted temperature reduction a city would spend money on, so "
                "an uncited constant here would be a fabricated number"
            ),
        )
    )
    providers.append(
        UnavailableProvider(
            name="openness_proxy",
            fields=("openness_proxy",),
            reason="needs building heights, which no wired source provides yet",
        )
    )

    return providers
