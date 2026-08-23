"""Feature providers — the contract enrichment is built on.

Every provider answers for a batch of tiles and returns, for each one, either a
value or `None`. `None` means *this dataset does not cover this tile*. It is never
substituted with 0, an average, or a nearest-neighbour guess.

That rule is the whole design. NLCD has gaps, elevation tiles have voids, and a
tile can fall outside every census block group. A provider that returned 0% canopy
for a tile it has no data about would tell the model that a forest is bare asphalt,
and the model would attribute heat to the wrong cause on a map a city acts on.

Providers declare their **native resolution** alongside their values. SVI is
published at census-tract scale — far coarser than a 60 m tile — so every tile in a
tract inherits one score. The UI must be able to say so, which means the resolution
has to travel with the data rather than living in a comment.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Final

import structlog

from .grid import Tile

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    """What a provider is and how good its answers are.

    Recorded per provider so the Methods page can list every input dataset with its
    real resolution and vintage, rather than implying the whole analysis is at tile
    resolution.
    """

    name: str
    #: Native resolution in metres. `None` for a vector source with no raster grid.
    resolution_m: float | None
    #: Human description of the source, reproduced in the provenance table.
    source: str
    #: Year or version of the underlying data.
    vintage: str


@dataclass(slots=True)
class ProviderResult:
    """One provider's answers for a batch.

    `values` maps tile_key → {field: value | None}. A tile absent from the mapping
    is treated identically to one mapped to all-None; both mean "no data", and
    conflating them is safe because neither asserts a measurement.
    """

    info: ProviderInfo
    values: dict[str, dict[str, float | None]] = field(default_factory=dict)
    #: Tiles the provider could not answer for, with the reason. Surfaced in the
    #: coverage report so a sparse layer is explained rather than merely sparse.
    misses: dict[str, str] = field(default_factory=dict)

    def coverage(self, total: int) -> float:
        """Fraction of the batch that received at least one non-null value."""
        if total == 0:
            return 0.0
        answered = sum(
            1
            for fields in self.values.values()
            if any(value is not None for value in fields.values())
        )
        return answered / total


class FeatureProvider(ABC):
    """A source of per-tile features."""

    @property
    @abstractmethod
    def info(self) -> ProviderInfo: ...

    @property
    @abstractmethod
    def fields(self) -> tuple[str, ...]:
        """Column names this provider populates in `tile_features`."""

    @abstractmethod
    def fetch(self, tiles: list[Tile]) -> ProviderResult:
        """Answer for a batch of tiles. Must not raise on partial coverage."""

    def is_available(self) -> bool:
        """Whether the provider can run at all.

        Separate from `fetch` so the pipeline can report "NLCD raster not present"
        once, up front, instead of accumulating one miss per tile and producing a
        result that looks like genuine data sparsity.
        """
        return True


class UnavailableProvider(FeatureProvider):
    """Stands in for a provider whose data or dependency is missing.

    Returns nulls for every field and records one reason. This exists so the
    pipeline runs to completion with an honest, explicitly-empty column rather than
    either crashing or — far worse — silently omitting the field so that downstream
    code fills it with a default.
    """

    def __init__(
        self, *, name: str, fields: tuple[str, ...], reason: str
    ) -> None:
        self._name = name
        self._fields = fields
        self._reason = reason

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name=self._name,
            resolution_m=None,
            source=f"UNAVAILABLE: {self._reason}",
            vintage="n/a",
        )

    @property
    def fields(self) -> tuple[str, ...]:
        return self._fields

    def is_available(self) -> bool:
        return False

    def fetch(self, tiles: list[Tile]) -> ProviderResult:
        log.warning(
            "provider.unavailable",
            provider=self._name,
            reason=self._reason,
            tiles=len(tiles),
            fields=list(self._fields),
        )
        return ProviderResult(
            info=self.info,
            values={
                tile.tile_key: dict.fromkeys(self._fields, None) for tile in tiles
            },
            misses={tile.tile_key: self._reason for tile in tiles},
        )


# ═════════════════════════════════════════════════════════════════════════════
# Derived features — computed from the grid alone, always available
# ═════════════════════════════════════════════════════════════════════════════


class GeometryProvider(FeatureProvider):
    """Features derivable from a tile's position, with no external dataset.

    Always available, which makes it the one provider guaranteed to contribute. The
    model needs latitude as a feature and the hour/day-of-year come from the request,
    so these are never missing.
    """

    def __init__(self, *, hour_utc: int | None = None, doy: int | None = None) -> None:
        self._hour_utc = hour_utc
        self._doy = doy

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name="geometry",
            resolution_m=None,
            source="Derived from the tile grid and the measurement window",
            vintage="n/a",
        )

    @property
    def fields(self) -> tuple[str, ...]:
        return ("latitude", "hour_utc", "doy")

    def fetch(self, tiles: list[Tile]) -> ProviderResult:
        return ProviderResult(
            info=self.info,
            values={
                tile.tile_key: {
                    "latitude": tile.centroid_lat,
                    "hour_utc": (
                        None if self._hour_utc is None else float(self._hour_utc)
                    ),
                    "doy": None if self._doy is None else float(self._doy),
                }
                for tile in tiles
            },
        )


#: Fields every enrichment run must produce a column for, populated or null.
#: Declared here so a provider that silently stops emitting a field is caught by
#: `enrich`'s completeness check rather than by a model training on a missing column.
REQUIRED_FEATURE_FIELDS: Final[tuple[str, ...]] = (
    "canopy_pct",
    "impervious_pct",
    "building_pct",
    "water_pct",
    "grass_shrub_pct",
    "albedo_proxy",
    "openness_proxy",
    "elevation_m",
    "local_relief_m",
    "dist_to_water_m",
    "hour_utc",
    "doy",
    "district_mean_c",
    "latitude",
)

#: Fields carried on a tile row that the model does *not* train on.
#:
#: Population and equity attributes answer "who is exposed", not "how hot is this
#: tile", so feeding them to a temperature model would be a leak. They are still
#: per-tile values, because the exposure and equity views multiply a temperature
#: change by the people it affects, which is the step that turns degrees into
#: person-heat-hours.
#:
#: They live in the `exposure` table, NOT in `tile_features`. Enrichment produces
#: one row carrying both, and the pipeline splits it before writing: the model's
#: inputs go to tile_features, these go to exposure. Handing the whole row to
#: `upsert_features` raises KeyError: 'population' against the excluded columns.
#:
#: Split out from REQUIRED_FEATURE_FIELDS rather than added to it: on 2026-08-21
#: the census providers answered 144/144 tiles at full coverage and enrich_tiles
#: discarded every value, because a row was seeded only with the required fields
#: and anything else was dropped by `if field_name not in row`. The providers
#: logged success, the report showed coverage 1.0, and population was null.
EXPOSURE_FIELDS: Final[tuple[str, ...]] = (
    "population",
    "pct_over65",
    "pct_poverty",
)

#: Every field a provider may legitimately emit onto a tile row.
ENRICHABLE_FIELDS: Final[tuple[str, ...]] = (
    *REQUIRED_FEATURE_FIELDS,
    *EXPOSURE_FIELDS,
)
