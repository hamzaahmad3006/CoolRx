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
from core.config import Settings
from geo import (
    apply_district_mean,
    build_grid,
    default_providers,
    enrich_tiles,
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

        grid, spec = build_grid(
            west=west, south=south, east=east, north=north,
            granularity_m=granularity,
        )
        log.info("pipeline.grid_built", tiles=spec.tile_count, epsg=spec.utm_epsg)

        _persist_analytic(
            session=session,
            tiles_repo=tiles_repo,
            project_id=project_id,
            grid=grid,
            result=tcm,
            analytic="tcm",
            granularity=granularity,
            start_date=start_date,
            start_time=start_time,
            threshold_c=None,
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
                grid=grid,
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
        providers = default_providers(hour_utc=hour_utc, doy=doy)
        feature_rows, enrichment = enrich_tiles(grid, providers)

        district_mean = _stat(tcm.result, "mean")
        apply_district_mean(feature_rows, district_mean)
        tiles_repo.upsert_features(project_id=project_id, rows=feature_rows)

        # ── Exposure ─────────────────────────────────────────────────────────
        jobs.advance(job_id, stage="computing_exposure", progress_pct=75)
        # Census joins live behind the same provider contract; until they are
        # wired the exposure table stays empty rather than carrying invented
        # populations, and the priority ranking falls back to raw hours.

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
            tile_count=len(grid),
            ladder_tiles=len(ladders),
            wanted_ladder=build_ladder_steps,
        )

        return DiagnoseOutcome(
            tile_count=len(grid),
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
    grid: list[Any],
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
        units=stats.get("units"),
    )

    values = _values_by_index(result.result)
    rows = [
        TileRow(
            tile_key=tile.tile_key,
            west=tile.west,
            south=tile.south,
            east=tile.east,
            north=tile.north,
            # None where the response had no value for this cell. Never zero.
            value=values.get(index),
        )
        for index, tile in enumerate(grid)
    ]
    tiles_repo.bulk_insert_tiles(
        project_id=project_id, analytic_run_id=run.id, rows=rows
    )
    return run


def _values_by_index(payload: dict[str, Any]) -> dict[int, float | None]:
    """Extract per-cell values from a heatmap response.

    The response shape is not fully documented (SRS C-6), so several plausible
    containers are tried and anything unrecognised yields no values rather than a
    guess — an empty layer with a visible coverage figure beats a fabricated one.
    """
    for key in ("data", "values", "grid", "cells", "heatmap"):
        candidate = payload.get(key)
        if isinstance(candidate, list) and candidate:
            out: dict[int, float | None] = {}
            for index, item in enumerate(candidate):
                if isinstance(item, (int, float)):
                    out[index] = float(item)
                elif isinstance(item, dict):
                    for value_key in ("value", "temperature", "tcm", "hours"):
                        raw = item.get(value_key)
                        if isinstance(raw, (int, float)):
                            out[index] = float(raw)
                            break
            if out:
                return out

    log.warning(
        "pipeline.unrecognised_response_shape",
        keys=sorted(payload)[:12],
        detail="no per-cell values extracted; layer will be empty, not invented",
    )
    return {}


def _stat(payload: dict[str, Any], name: str) -> float | None:
    stats = payload.get("stats_data", {}) or {}
    value = stats.get(name)
    return float(value) if isinstance(value, (int, float)) else None


def _build_ladders(
    *,
    client: FortyGuardClient,
    session: Session,
    tiles_repo: TileRepository,
    project_id: uuid.UUID,
    bounds: tuple[float, float, float, float],
    grid: list[Any],
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
        _persist_analytic(
            session=session,
            tiles_repo=tiles_repo,
            project_id=project_id,
            grid=grid,
            result=result,
            analytic="exceedance",
            granularity=granularity,
            start_date=start_date,
            start_time=start_time,
            threshold_c=rung_threshold,
        )

        values = _values_by_index(result.result)
        by_step[step] = {
            tile.tile_key: values.get(index) for index, tile in enumerate(grid)
        }

    ladders: dict[str, TileLadder] = {}
    for tile in grid:
        ladder = build_ladder(
            tile_key=tile.tile_key,
            base_threshold_c=threshold_c,
            hours_by_step={
                step: values.get(tile.tile_key) for step, values in by_step.items()
            },
            steps=steps,
        )
        # None means a rung was missing. The tile is excluded from hours-avoided
        # accounting rather than being given an interpolated measurement.
        if ladder is not None:
            ladders[tile.tile_key] = ladder

    log.info(
        "pipeline.ladders_built",
        complete=len(ladders),
        total=len(grid),
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
                "predicted_anomaly_c": Decimal(
                    str(round(prediction.value - district_mean_c, 3))
                ),
                "ci_low_c": Decimal(str(round(prediction.low - district_mean_c, 3))),
                "ci_high_c": Decimal(str(round(prediction.high - district_mean_c, 3))),
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
