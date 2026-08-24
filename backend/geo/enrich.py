"""Enrichment orchestration.

Runs every provider over a tile batch and merges the answers into one row per tile.
Three properties are enforced here rather than trusted:

  1. **Every required field exists on every row**, populated or explicitly null. A
     provider that stops emitting a field is caught here, not by a model that
     silently trains on a column of nulls.
  2. **Null never becomes zero.** The merge only writes a value when a provider
     supplies a non-null one, so a later provider cannot overwrite a real reading
     with a missing one and no provider can default a field into existence.
  3. **Coverage is measured and returned.** A run where NLCD answered for 40% of
     tiles is usable, but the UI has to be able to say so.

Providers are ordered. When two answer for the same field the first one wins, so a
high-resolution source is never overwritten by a coarser fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from .grid import Tile
from .providers import (
    ENRICHABLE_FIELDS,
    FeatureProvider,
    ProviderInfo,
    ProviderResult,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FieldCoverage:
    field_name: str
    populated: int
    total: int

    @property
    def fraction(self) -> float:
        return self.populated / self.total if self.total else 0.0


@dataclass(slots=True)
class EnrichmentReport:
    """What the run actually produced.

    Returned alongside the rows because a caller that only received rows could not
    distinguish "this district genuinely has no tree canopy" from "the canopy
    dataset was unavailable" — and those lead to opposite recommendations.
    """

    tile_count: int
    providers: list[ProviderInfo] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    field_coverage: list[FieldCoverage] = field(default_factory=list)

    def coverage_of(self, field_name: str) -> float:
        for coverage in self.field_coverage:
            if coverage.field_name == field_name:
                return coverage.fraction
        return 0.0

    @property
    def fully_null_fields(self) -> list[str]:
        """Fields no provider answered for. These must be caveated, not plotted."""
        return [c.field_name for c in self.field_coverage if c.populated == 0]


def enrich_tiles(
    tiles: list[Tile], providers: list[FeatureProvider]
) -> tuple[list[dict[str, float | None]], EnrichmentReport]:
    """Merge every provider's answers into one row per tile.

    Rows are shaped for `TileRepository.upsert_features`: each carries `tile_key`
    plus every field in `ENRICHABLE_FIELDS` -- the model's inputs and the
    exposure attributes the equity views need.
    """
    if not tiles:
        return [], EnrichmentReport(tile_count=0)

    # Start from all-null. Every field therefore exists on every row from the
    # outset, and a provider's absence leaves a null rather than a missing key.
    merged: dict[str, dict[str, float | None]] = {
        tile.tile_key: dict.fromkeys(ENRICHABLE_FIELDS, None) for tile in tiles
    }

    report = EnrichmentReport(tile_count=len(tiles))

    for provider in providers:
        if not provider.is_available():
            report.unavailable.append(provider.info.name)

        result: ProviderResult = provider.fetch(tiles)
        report.providers.append(result.info)

        unknown = set(provider.fields) - set(ENRICHABLE_FIELDS)
        if unknown:
            # Loud, because a provider emitting a field the schema has no column
            # for means the two have drifted apart and the value is being dropped.
            log.error(
                "enrich.unknown_fields",
                provider=result.info.name,
                fields=sorted(unknown),
            )

        for tile_key, values in result.values.items():
            row = merged.get(tile_key)
            if row is None:
                continue
            for field_name, value in values.items():
                if field_name not in row:
                    continue
                # Only write a real value. A null from a later provider must not
                # erase an earlier provider's reading, and first-wins ordering means
                # a coarse fallback cannot overwrite a fine-grained source.
                if value is not None and row[field_name] is None:
                    row[field_name] = value

        log.info(
            "enrich.provider_done",
            provider=result.info.name,
            coverage=round(result.coverage(len(tiles)), 4),
            misses=len(result.misses),
        )

    report.field_coverage = [
        FieldCoverage(
            field_name=name,
            populated=sum(1 for row in merged.values() if row[name] is not None),
            total=len(tiles),
        )
        for name in ENRICHABLE_FIELDS
    ]

    rows = [{"tile_key": key, **values} for key, values in merged.items()]

    empty = report.fully_null_fields
    if empty:
        log.warning(
            "enrich.fields_entirely_null",
            fields=empty,
            detail=(
                "No provider answered for these. They must be shown as unavailable "
                "rather than plotted as zero."
            ),
        )

    log.info(
        "enrich.complete",
        tiles=len(rows),
        providers=len(report.providers),
        unavailable=report.unavailable,
        fully_null=len(empty),
    )
    return rows, report


def apply_district_mean(
    rows: list[dict[str, float | None]], district_mean_c: float | None
) -> None:
    """Stamp the district mean onto every row, in place.

    A single value per project rather than a provider: it is derived from the
    FortyGuard temperature field after enrichment, and the model uses each tile's
    anomaly *against* it. Passing None leaves the column null rather than zero,
    because a district mean of 0 °C would make every tile look extraordinarily hot.
    """
    if district_mean_c is None:
        return
    for row in rows:
        row["district_mean_c"] = district_mean_c
