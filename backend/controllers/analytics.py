"""Analytics read controller — tiles, stats, enrichment, priorities.

Every read here can legitimately return nothing: a project whose diagnosis has not
run has no tiles, no attribution and no priorities. That is a precondition failure
rather than a missing resource, and it is reported as one so the UI can say "run a
diagnosis first" instead of "not found".

Coverage is reported alongside every tile layer. A layer where 40% of tiles are
null is a usable result with a caveat, and returning the null count is what lets
the map say so rather than silently looking sparse.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from clients.fortyguard.parsing import read_stat
from repositories.tables import AnalyticRun, FgRequest
from repositories.tiles import TileRepository
from schemas.analytics import (
    AttributionListResponse,
    AttributionResponse,
    ExposureListResponse,
    FgStats,
    PriorityResponse,
    StatsResponse,
    TileFeature,
    TileProperties,
    TilesResponse,
)
from schemas.common import AnalyticType

from .adapters import (
    analytic_run_to_response,
    attribution_to_response,
    exposure_to_response,
)
from .errors import NotFoundError, PreconditionMissingError

log = structlog.get_logger(__name__)

_NO_DIAGNOSIS = (
    "No diagnosis has been run for this project yet. Start one to produce "
    "temperature layers."
)


class AnalyticsController:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._tiles = TileRepository(session)

    # ── Tiles ────────────────────────────────────────────────────────────────

    def tiles(self, project_id: uuid.UUID, analytic: AnalyticType) -> TilesResponse:
        run = self._latest_run(project_id, analytic)
        features_raw = self._tiles.tile_geojson_for_run(run.id)
        with_values, total = self._tiles.coverage(run.id)

        features = [
            TileFeature(
                id=str(item["id"]),
                geometry=item["geometry"],
                properties=TileProperties.model_validate(item["properties"]),
            )
            for item in features_raw
        ]

        return TilesResponse(
            analytic=analytic,
            # Echoed from the response's own stats_data, never assumed (SRS C-4).
            units=run.units,
            threshold_c=float(run.threshold_c) if run.threshold_c is not None else None,
            granularity=run.granularity_m,  # type: ignore[arg-type]
            tile_count=total,
            null_count=total - with_values,
            activity_id=self._activity_id_for(run),
            features=features,
        )

    def stats(self, project_id: uuid.UUID) -> StatsResponse:
        runs = list(
            self._session.execute(
                select(AnalyticRun)
                .where(AnalyticRun.project_id == project_id)
                .order_by(AnalyticRun.created_at.desc())
            ).scalars()
        )
        if not runs:
            raise PreconditionMissingError(message=_NO_DIAGNOSIS, field="projectId")

        # The tcm run carries the temperature field the district mean derives from;
        # falling back to the newest run keeps the endpoint usable when only an
        # exceedance run exists.
        primary = next((r for r in runs if r.analytic_type == "tcm"), runs[0])
        stats = self._stats_of(primary)

        return StatsResponse(
            analytic_runs=[
                analytic_run_to_response(run, self._activity_id_for(run))
                for run in runs
            ],
            stats=stats,
            hotspot_cutoff=self._hotspot_cutoff(stats),
            district_mean_c=stats.mean,
        )

    def _stats_of(self, run: AnalyticRun) -> FgStats:
        """The run's statistics, read through the same helper the pipeline uses.

        `FgStats` is flat -- min, max, mean, std -- and the API is not. The real
        response nests them under `stats_data.temperature_stats` and names them
        `minimum`, `maximum`, `standard_deviation`. Validating the stored blob
        straight into the flat model therefore matched nothing and returned all
        nulls, so `/stats` published an empty statistics block for every project
        and the map legend had no domain to scale to. Nothing errored: every
        field is legitimately optional, because the contents genuinely vary by
        analytic type.

        `read_stat` already knew the shape -- it handles the documented
        capitalisation and the lower-cased spelling the live API actually sends.
        It expects the whole result, so the stored `stats_data` is rewrapped.

        `median` is not published by the API and stays null rather than being
        approximated from the mean.
        """
        raw = {"stats_data": run.stats or {}}
        with_values, _total = self._tiles.coverage(run.id)
        return FgStats(
            min=read_stat(raw, "min"),
            max=read_stat(raw, "max"),
            mean=read_stat(raw, "mean"),
            median=None,
            std=read_stat(raw, "std"),
            count=with_values,
            # Echoed from the run, never assumed. The live API sends no units
            # field, so this is null rather than a guessed "celsius" (N-3).
            units=run.units,
        )

    @staticmethod
    def _hotspot_cutoff(stats: FgStats) -> float | None:
        """One standard deviation above the mean.

        Returned as None rather than guessed when either input is missing — a
        cutoff derived from an assumed spread would draw a hotspot boundary that
        nothing in the data supports.
        """
        if stats.mean is None or stats.std is None:
            return None
        return stats.mean + stats.std

    # ── Enrichment ───────────────────────────────────────────────────────────

    def attribution(self, project_id: uuid.UUID) -> AttributionListResponse:
        rows = self._tiles.attribution_for(project_id)
        if not rows:
            raise PreconditionMissingError(
                message=(
                    "No attribution has been computed for this project yet. It is "
                    "produced during diagnosis."
                ),
                field="projectId",
            )
        return AttributionListResponse(
            items=[attribution_to_response(row) for row in rows]
        )

    def attribution_for_tile(
        self, project_id: uuid.UUID, tile_key: str
    ) -> AttributionResponse:
        row = self._tiles.attribution_for_tile(project_id, tile_key)
        if row is None:
            raise NotFoundError(
                message=f"No attribution for tile {tile_key}.", field="tileKey"
            )
        return attribution_to_response(row)

    def exposure(self, project_id: uuid.UUID) -> ExposureListResponse:
        rows = self._tiles.exposure_for(project_id)
        if not rows:
            raise PreconditionMissingError(
                message=(
                    "No exposure data for this project yet. It is joined during "
                    "diagnosis."
                ),
                field="projectId",
            )
        return ExposureListResponse(items=[exposure_to_response(row) for row in rows])

    # ── Priorities ───────────────────────────────────────────────────────────

    def priorities(
        self, project_id: uuid.UUID, equity_lambda: float, threshold_c: float
    ) -> PriorityResponse:
        """Ranked tiles.

        Computed on read rather than stored, because the ranking depends on λ — a
        policy choice the user changes with a slider. Persisting one ranking would
        mean either recomputing on every change anyway or serving a stale order
        that silently disagrees with the λ shown on screen.
        """
        from optimizer.priorities import rank_tiles

        items = rank_tiles(
            session=self._session,
            project_id=project_id,
            equity_lambda=equity_lambda,
            threshold_c=threshold_c,
        )
        return PriorityResponse(
            items=items,
            equity_lambda=equity_lambda,
            threshold_c=threshold_c,
        )

    # ── Internals ────────────────────────────────────────────────────────────

    def _latest_run(self, project_id: uuid.UUID, analytic: AnalyticType) -> AnalyticRun:
        stmt = (
            select(AnalyticRun)
            .where(
                AnalyticRun.project_id == project_id,
                AnalyticRun.analytic_type == analytic,
            )
            .order_by(AnalyticRun.created_at.desc())
            .limit(1)
        )
        run = self._session.execute(stmt).scalar_one_or_none()
        if run is None:
            raise PreconditionMissingError(
                message=(
                    f"No '{analytic}' layer for this project yet. {_NO_DIAGNOSIS}"
                ),
                field="analytic",
                details={"analytic": analytic},
            )
        return run

    def _activity_id_for(self, run: AnalyticRun) -> str | None:
        """The FortyGuard handle behind a run — the provenance anchor (P2)."""
        stmt = select(FgRequest.activity_id).where(FgRequest.id == run.fg_request_id)
        row = self._session.execute(stmt).first()
        return None if row is None else row[0]
