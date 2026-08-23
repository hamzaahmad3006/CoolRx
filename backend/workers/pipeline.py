"""The diagnose and plan pipelines.

Where every module built so far is finally connected: FortyGuard → geo → ml →
optimizer → agent → persistence.

Two rules hold throughout, and both exist because a heat plan that quietly degrades
is more dangerous than one that visibly fails:

  * **A stage that cannot produce real data does not produce fake data.** It raises,
    or it degrades the job with a reason the UI shows. There is no code path that
    substitutes a plausible number for a missing one.
  * **Progress is reported before each stage, not after.** A user watching a
    four-minute pipeline needs to know what is running now, not what finished.

The ladder is built with 11 `exceedance` calls at T…T+10. Those are the expensive
part of a diagnosis, and they are issued through the client's cache, so a re-run at
the same thresholds costs nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from clients.fortyguard.client import FortyGuardClient
from clients.fortyguard.parsing import parse_heatmap, read_stat
from core.config import Settings
from geo import (
    EXPOSURE_FIELDS,
    Tile as GridTile,
    apply_district_mean,
    default_providers,
    enrich_tiles,
    estimate_tile_count,
    tile_key,
)
from ml import (
    ModelNotTrained,
    OutOfSupport,
    TemperatureModel,
)
from optimizer import (
    TileLadder,
    build_ladder,
)
from repositories.fg_cache import FgCacheRepository
from repositories.jobs import JobRepository
from repositories.projects import ProjectRepository
from repositories.tables import FgRequest
from repositories.tiles import TileRepository, TileRow

log = structlog.get_logger(__name__)


class PipelineError(RuntimeError):
    """A stage could not complete and no usable result exists."""


@dataclass(slots=True)
class DiagnoseOutcome:
    tile_count: int
    ladder_tiles: int
    attributed_tiles: int
    degraded_reason: str | None = None


# ═════════════════════════════════════════════════════════════════════════════
# Diagnose
# ═════════════════════════════════════════════════════════════════════════════


def run_diagnose_pipeline(
    *,
    session: Session,
    settings: Settings,
    job_id: uuid.UUID,
    project_id: uuid.UUID,
    start_date: str,
    start_time: str,
    granularity: int,
    threshold_c: float,
    build_ladder_steps: bool,
) -> DiagnoseOutcome:
    """Fetch, tile, enrich and attribute one district."""
    jobs = JobRepository(session)
    projects = ProjectRepository(session)
    tiles_repo = TileRepository(session)
    cache = FgCacheRepository(session)

    jobs.advance(job_id, stage="validating", progress_pct=5)

    bounds = projects.aoi_bounds(project_id)
    if bounds is None:
        raise PipelineError(f"Project {project_id} has no stored geometry.")
    west, south, east, north = bounds

    client = FortyGuardClient(
        settings,
        cache_get=cache.get_result,
        cache_put=cache.put_result,
        audit=cache.record,
        submissions_today=cache.submissions_today,
    )

    try:
        # ── Temperature field ────────────────────────────────────────────────
        jobs.advance(job_id, stage="fetching_temperature", progress_pct=25)

        tcm = _fetch_analytic(
            client,
            bounds=bounds,
            analytic="tcm",
            granularity=granularity,
            start_date=start_date,
            start_time=start_time,
        )

        # Our own grid is used only for the pre-flight tile estimate. The tiles the
        # values attach to come from the API's `map_data`, because they are the
        # ones the measurements were taken on.
        expected = estimate_tile_count(
            west=west, south=south, east=east, north=north,
            granularity_m=granularity,
        )

        _tcm_run, tcm_parsed = _persist_analytic(
            session=session,
            tiles_repo=tiles_repo,
            project_id=project_id,
            result=tcm,
            analytic="tcm",
            granularity=granularity,
            start_date=start_date,
            start_time=start_time,
            threshold_c=None,
        )
        log.info(
            "pipeline.tiles_received",
            returned=len(tcm_parsed.tiles),
            estimated=expected,
            with_values=tcm_parsed.with_values,
            value_key=tcm_parsed.value_key,
        )

        # ── Ladder ───────────────────────────────────────────────────────────
        jobs.advance(job_id, stage="building_ladder", progress_pct=45)

        ladders: dict[str, TileLadder] = {}
        if build_ladder_steps:
            ladders = _build_ladders(
                client=client,
                session=session,
                tiles_repo=tiles_repo,
                project_id=project_id,
                bounds=bounds,
                granularity=granularity,
                start_date=start_date,
                start_time=start_time,
                threshold_c=threshold_c,
                steps=settings.fg_ladder_steps,
            )

        # ── Enrichment ───────────────────────────────────────────────────────
        jobs.advance(job_id, stage="enriching_features", progress_pct=60)

        hour_utc = int(start_time.split(":")[0])
        doy = date.fromisoformat(start_date).timetuple().tm_yday
        # The key is passed in rather than read inside `geo`, which deliberately
        # knows nothing about config, FortyGuard or the database.
        providers = default_providers(
            hour_utc=hour_utc,
            doy=doy,
            census_api_key=settings.census_api_key,
        )
        # Enriched against the API's tiles, so a feature row exists for exactly the
        # tiles that carry a measurement.
        enrichment_tiles = [
            GridTile(
                tile_key=tile_key(tile.centroid_lon, tile.centroid_lat),
                west=tile.west,
                south=tile.south,
                east=tile.east,
                north=tile.north,
                centroid_lon=tile.centroid_lon,
                centroid_lat=tile.centroid_lat,
            )
            for tile in tcm_parsed.tiles
        ]
        feature_rows, enrichment = enrich_tiles(enrichment_tiles, providers)

        district_mean = read_stat(tcm.result, "mean")
        apply_district_mean(feature_rows, district_mean)

        # The enriched row carries the model's inputs *and* the census answers,
        # because both come from the same provider chain. They belong in
        # different tables: `tile_features` holds what the model trains on, and
        # `exposure` holds who is affected. Writing the whole row to
        # `upsert_features` raised KeyError: 'population' against the excluded
        # columns, because tile_features has no such column and never has.
        exposure_rows = [
            {
                "tile_key": row["tile_key"],
                **{field: row.get(field) for field in EXPOSURE_FIELDS},
            }
            for row in feature_rows
        ]
        model_rows = [
            {k: v for k, v in row.items() if k not in EXPOSURE_FIELDS}
            for row in feature_rows
        ]
        tiles_repo.upsert_features(project_id=project_id, rows=model_rows)

        # ── Exposure ─────────────────────────────────────────────────────────
        jobs.advance(job_id, stage="computing_exposure", progress_pct=75)
        # Populated from the census providers rather than left empty. A tile with
        # no census answer keeps a null population, which the priority ranking
        # already handles by falling back to raw hours -- an invented population
        # would silently reweight the whole plan.
        written = tiles_repo.upsert_exposure(
            project_id=project_id, rows=exposure_rows
        )
        with_population = sum(
            1 for row in exposure_rows if row.get("population") is not None
        )
        log.info(
            "pipeline.exposure_written",
            rows=written,
            with_population=with_population,
            tiles=len(exposure_rows),
        )

        # ── Attribution ──────────────────────────────────────────────────────
        jobs.advance(job_id, stage="attributing", progress_pct=90)
        attributed = _attribute(
            session=session,
            settings=settings,
            tiles_repo=tiles_repo,
            project_id=project_id,
            feature_rows=feature_rows,
            district_mean_c=district_mean,
        )

        jobs.advance(job_id, stage="finalizing", progress_pct=100)

        degraded = _degradation_reason(
            enrichment_unavailable=enrichment.unavailable,
            attributed=attributed,
            tile_count=len(tcm_parsed.tiles),
            ladder_tiles=len(ladders),
            wanted_ladder=build_ladder_steps,
        )

        return DiagnoseOutcome(
            tile_count=len(tcm_parsed.tiles),
            ladder_tiles=len(ladders),
            attributed_tiles=attributed,
            degraded_reason=degraded,
        )
    finally:
        client.close()


def _fetch_analytic(
    client: FortyGuardClient,
    *,
    bounds: tuple[float, float, float, float],
    analytic: str,
    granularity: int,
    start_date: str,
    start_time: str,
    threshold_c: float | None = None,
) -> Any:
    """One heatmap call. Cache and fixtures are handled inside the client."""
    west, south, east, north = bounds
    payload: dict[str, Any] = {
        "polygon_aoi": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [west, south],
                                [east, south],
                                [east, north],
                                [west, north],
                                [west, south],
                            ]
                        ],
                    },
                }
            ],
        },
        "date_time": {
            "start_date": start_date,
            "start_time": start_time,
            "filter_type": 1,
        },
        "granularity": granularity,
        "analytic_type": analytic,
    }
    if threshold_c is not None:
        payload["threshold"] = threshold_c
        payload["direction"] = "above"

    return client.submit_and_wait("heatmap", payload)


def _persist_analytic(
    *,
    session: Session,
    tiles_repo: TileRepository,
    project_id: uuid.UUID,
    result: Any,
    analytic: str,
    granularity: int,
    start_date: str,
    start_time: str,
    threshold_c: float | None,
) -> Any:
    """Store one analytic run and its tiles."""
    fg_row = session.execute(
        select(FgRequest).where(FgRequest.request_hash == result.request_hash)
    ).scalar_one_or_none()
    if fg_row is None:
        raise PipelineError(
            "The FortyGuard request was not recorded, so this run would have no "
            "provenance anchor. Refusing to persist untraceable tiles."
        )

    stats = result.result.get("stats_data", {}) or {}
    units = _units_of(result.result)
    run = tiles_repo.create_run(
        project_id=project_id,
        fg_request_id=fg_row.id,
        analytic_type=analytic,
        granularity_m=granularity,
        start_date=date.fromisoformat(start_date),
        start_time=time.fromisoformat(f"{start_time}:00"),
        filter_type=1,
        stats=stats,
        threshold_c=threshold_c,
        direction="above" if threshold_c is not None else None,
        units=units,
    )

    # The API returns its own tile polygons, so values are attached to those rather
    # than index-matched onto our generated grid. Index matching would silently
    # mis-assign every temperature the moment their tiling differed from ours by a
    # single cell, and nothing downstream could detect it.
    parsed = parse_heatmap(result.result)
    rows = [
        TileRow(
            tile_key=tile_key(tile.centroid_lon, tile.centroid_lat),
            west=tile.west,
            south=tile.south,
            east=tile.east,
            north=tile.north,
            # None where the response carried no value for this cell. Never zero.
            value=tile.value,
        )
        for tile in parsed.tiles
    ]
    tiles_repo.bulk_insert_tiles(
        project_id=project_id, analytic_run_id=run.id, rows=rows
    )
    return run, parsed


def _units_of(payload: dict[str, Any]) -> str | None:
    """Units as reported, never assumed (SRS C-4)."""
    return parse_heatmap(payload).units


def _build_ladders(
    *,
    client: FortyGuardClient,
    session: Session,
    tiles_repo: TileRepository,
    project_id: uuid.UUID,
    bounds: tuple[float, float, float, float],
    granularity: int,
    start_date: str,
    start_time: str,
    threshold_c: float,
    steps: int,
) -> dict[str, TileLadder]:
    """The exceedance ladder: hours above T, T+1 … T+steps.

    Each rung is a separate call, issued through the cache, so re-running a
    diagnosis at the same thresholds is free.
    """
    by_step: dict[int, dict[str, float | None]] = {}

    for step in range(steps + 1):
        rung_threshold = threshold_c + step
        result = _fetch_analytic(
            client,
            bounds=bounds,
            analytic="exceedance",
            granularity=granularity,
            start_date=start_date,
            start_time=start_time,
            threshold_c=rung_threshold,
        )
        _run, parsed = _persist_analytic(
            session=session,
            tiles_repo=tiles_repo,
            project_id=project_id,
            result=result,
            analytic="exceedance",
            granularity=granularity,
            start_date=start_date,
            start_time=start_time,
            threshold_c=rung_threshold,
        )

        # Keyed by tile key, not by array position. Rungs are separate API calls
        # and their tile ordering is not guaranteed to match; position-matching
        # would build a ladder from eleven different places on the ground.
        by_step[step] = {
            tile_key(tile.centroid_lon, tile.centroid_lat): tile.value
            for tile in parsed.tiles
        }

    all_keys = set(by_step.get(0, {}))
    ladders: dict[str, TileLadder] = {}
    for key in all_keys:
        ladder = build_ladder(
            tile_key=key,
            base_threshold_c=threshold_c,
            hours_by_step={
                step: values.get(key) for step, values in by_step.items()
            },
            steps=steps,
        )
        # None means a rung was missing. The tile is excluded from hours-avoided
        # accounting rather than being given an interpolated measurement.
        if ladder is not None:
            ladders[key] = ladder

    log.info(
        "pipeline.ladders_built",
        complete=len(ladders),
        total=len(all_keys),
        steps=steps,
    )
    return ladders


def _attribute(
    *,
    session: Session,
    settings: Settings,
    tiles_repo: TileRepository,
    project_id: uuid.UUID,
    feature_rows: list[dict[str, float | None]],
    district_mean_c: float | None,
) -> int:
    """Per-tile SHAP attribution, if a trained model is available.

    A missing model is not an error. Attribution is an explanation layer; the
    temperature map, the ladder and the priority ranking are all still correct
    without it, so the run degrades rather than failing.
    """
    from pathlib import Path

    try:
        model = TemperatureModel.load(Path(settings.model_dir))
    except (ModelNotTrained, Exception) as exc:  # noqa: BLE001
        log.warning("pipeline.no_model", detail=str(exc))
        return 0

    if district_mean_c is None:
        log.warning(
            "pipeline.no_district_mean",
            detail="anomalies are relative to it; skipping attribution",
        )
        return 0

    rows: list[dict[str, Any]] = []
    for features in feature_rows:
        tile_key = str(features["tile_key"])
        vector = {k: v for k, v in features.items() if k != "tile_key"}

        try:
            prediction = model.predict(vector)
        except OutOfSupport:
            continue

        contributions = model.contributions(vector)
        rows.append(
            {
                "tile_key": tile_key,
                "model_version": model.model_version,
                # The model is trained on the anomaly against the district
                # baseline, so its output IS the anomaly. Subtracting the mean
                # again here would apply the correction twice and report every
                # tile as roughly one district-mean too cold.
                "predicted_anomaly_c": Decimal(str(round(prediction.value, 3))),
                "ci_low_c": Decimal(str(round(prediction.low, 3))),
                "ci_high_c": Decimal(str(round(prediction.high, 3))),
                "shap": contributions,
                "top_driver": max(
                    contributions, key=lambda name: abs(contributions[name])
                ),
            }
        )

    if rows:
        tiles_repo.replace_attribution(project_id=project_id, rows=rows)
    return len(rows)


def _degradation_reason(
    *,
    enrichment_unavailable: list[str],
    attributed: int,
    tile_count: int,
    ladder_tiles: int,
    wanted_ladder: bool,
) -> str | None:
    """A single sentence naming what is missing, or None when nothing is.

    Surfaced on the job so the UI shows a caveat rather than the user discovering
    an empty panel and assuming the tool is broken.
    """
    problems: list[str] = []

    if enrichment_unavailable:
        problems.append(
            f"land-cover and terrain data unavailable ({', '.join(enrichment_unavailable)})"
        )
    if attributed == 0:
        problems.append("no trained model, so heat drivers are not attributed")
    if wanted_ladder and ladder_tiles == 0:
        problems.append("the exceedance ladder is incomplete, so impact stays in degrees")
    elif wanted_ladder and ladder_tiles < tile_count * 0.5:
        problems.append(
            f"only {ladder_tiles} of {tile_count} blocks have a complete ladder"
        )

    return "; ".join(problems).capitalize() + "." if problems else None
