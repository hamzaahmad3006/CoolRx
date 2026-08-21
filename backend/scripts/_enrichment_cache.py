"""Build and cache the training feature matrix from recorded FortyGuard tiles.

Separate from `train_model.py` so that assembling the matrix can be re-run,
inspected and tested without going near a booster.

## What this does

A recorded `tcm` fixture gives, per tile, a geometry and a measured temperature.
That temperature is the training label. The features come from the same provider
chain the live pipeline uses — `geo.default_providers` through `geo.enrich_tiles`
— so a row assembled here and a row assembled during a real diagnosis are
produced by the same code path. If they diverged, the model would be trained on
one distribution and asked to predict on another.

## Why it caches

Enriching a district is four to six requests to free public services, and a
retrain should not repeat them. The cache is keyed by district and holds the
assembled rows; deleting a file re-fetches that district.

The cache stores what the providers answered, including nulls. It never stores a
value the providers did not produce, so a cache hit and a fresh fetch make the
same claims.

## Null features

`albedo_proxy` and `openness_proxy` are null on every row: no provider sources
them. LightGBM handles missing values natively, so their presence in
`FEATURE_ORDER` costs nothing at fit time — but a constantly-null feature carries
no information, so the model will make no split on it, and a counterfactual that
changes only that feature will predict exactly zero cooling. That consequence is
recorded in `metrics.json` under `features_null` rather than left to be
discovered.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from geo import default_providers, enrich_tiles
from geo.grid import Tile
from ml.features import FEATURE_ORDER

log = structlog.get_logger(__name__)

#: Cache format. Bump when the row shape or the provider set changes in a way
#: that makes previously-cached rows wrong rather than merely stale.
CACHE_VERSION = 3


def _tile_key(parsed: Any, index: int) -> str:
    """A stable key for a parsed tile.

    `ParsedTile` carries geometry but no key, and `enrich_tiles` merges on one.
    The centroid is stable across runs for the same recorded response, which the
    row's position in the list is not once a fixture is re-harvested.
    """
    return f"{parsed.centroid_lon:.6f},{parsed.centroid_lat:.6f}"


def _to_tiles(parsed_tiles: list[Any]) -> tuple[list[Tile], dict[str, float]]:
    """Grid tiles for enrichment, plus the label for each key."""
    tiles: list[Tile] = []
    labels: dict[str, float] = {}

    for index, parsed in enumerate(parsed_tiles):
        if parsed.value is None:
            continue
        key = _tile_key(parsed, index)
        if key in labels:
            # The same ground measured twice in one district — keep the first so
            # a duplicated fixture cannot weight one tile twice in training.
            continue
        labels[key] = float(parsed.value)
        tiles.append(
            Tile(
                tile_key=key,
                west=parsed.west,
                south=parsed.south,
                east=parsed.east,
                north=parsed.north,
                centroid_lon=parsed.centroid_lon,
                centroid_lat=parsed.centroid_lat,
            )
        )

    return tiles, labels


def _hour_and_doy(parsed_tiles: list[Any]) -> tuple[int | None, int | None]:
    """Hour and day-of-year for the recorded observation, if it carries them.

    Returns (None, None) when unknown; `GeometryProvider` then leaves those
    columns null rather than stamping a guess onto every row.
    """
    for parsed in parsed_tiles:
        hour = getattr(parsed, "hour_utc", None)
        doy = getattr(parsed, "doy", None)
        if hour is not None and doy is not None:
            return int(hour), int(doy)
    return None, None


def enriched_rows(
    district: str,
    parsed_tiles: list[Any],
    cache_dir: Path,
    *,
    census_api_key: str | None = None,
    refresh: bool = False,
) -> tuple[list[dict[str, float | None]], list[float]]:
    """Feature rows and matching labels for one district.

    Rows carry exactly `FEATURE_ORDER`, in that order, so the caller can hand
    them straight to `TemperatureModel.fit`.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{district}.json"

    if cache_path.exists() and not refresh:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("cache_version") == CACHE_VERSION:
            log.info(
                "enrichment.cache_hit", district=district, rows=len(cached["rows"])
            )
            return cached["rows"], cached["labels"]
        log.info("enrichment.cache_stale", district=district)

    tiles, labels_by_key = _to_tiles(parsed_tiles)
    if not tiles:
        return [], []

    hour_utc, doy = _hour_and_doy(parsed_tiles)
    providers = default_providers(
        hour_utc=hour_utc, doy=doy, census_api_key=census_api_key
    )

    enriched, report = enrich_tiles(tiles, providers)

    # The district mean is not fetched: it is derived from the measurements
    # themselves, exactly as `apply_district_mean` derives it in the live
    # pipeline from the FortyGuard temperature field after enrichment.
    #
    # It is a feature rather than an afterthought because the model predicts an
    # absolute temperature and the other twelve features describe the *ground*,
    # not the day. Without it, a model trained on Phoenix and Tucson has nothing
    # to tell it that Las Vegas sits at a different baseline, and it predicts
    # Phoenix temperatures for Las Vegas ground: measured on 2026-08-21 that gave
    # an R2 of -1850 and interval coverage of zero on held-out ground.
    #
    # It cancels out of a counterfactual -- both sides of a delta carry the same
    # district mean -- so including it moves the level without touching the
    # cooling estimate, which is the number the product actually publishes.
    matched = [
        (row, labels_by_key[row["tile_key"]])
        for row in enriched
        if row.get("tile_key") in labels_by_key
    ]
    district_mean = (
        sum(label for _, label in matched) / len(matched) if matched else None
    )

    rows: list[dict[str, float | None]] = []
    labels: list[float] = []
    for row, label in matched:
        vector = {name: row.get(name) for name in FEATURE_ORDER}
        vector["district_mean_c"] = district_mean
        rows.append(vector)
        labels.append(label)

    cache_path.write_text(
        json.dumps(
            {
                "cache_version": CACHE_VERSION,
                "district": district,
                "rows": rows,
                "labels": labels,
                "coverage": {
                    field.field_name: field.populated for field in report.field_coverage
                },
                "unavailable": report.unavailable,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    log.info(
        "enrichment.built",
        district=district,
        rows=len(rows),
        unavailable=report.unavailable,
    )
    return rows, labels
