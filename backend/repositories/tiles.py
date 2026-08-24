"""Tile, analytic-run and per-tile enrichment persistence.

Tile counts are the reason this module is written around bulk operations rather
than ORM objects: a 10 mi² AOI at 60 m granularity is roughly 7,200 tiles, and
one INSERT per tile would dominate the pipeline's runtime (SRS §21).

`value` is nullable throughout and is never coerced to zero. A missing
measurement and a measurement of zero are different facts, and conflating them
would put a fabricated reading on a map.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .tables import AnalyticRun, Attribution, Exposure, Tile, TileFeature

log = structlog.get_logger(__name__)

#: Rows per executemany batch. Large enough to amortise round-trips, small enough
#: that a failed batch is cheap to retry.
BATCH_SIZE = 1_000


@dataclass(frozen=True, slots=True)
class TileRow:
    """One tile ready for insertion. `value` is None when the API omitted it."""

    tile_key: str
    west: float
    south: float
    east: float
    north: float
    value: float | None


class TileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Analytic runs ────────────────────────────────────────────────────────

    def create_run(
        self,
        *,
        project_id: uuid.UUID,
        fg_request_id: uuid.UUID,
        analytic_type: str,
        granularity_m: int,
        start_date: date,
        filter_type: int,
        stats: dict[str, Any],
        threshold_c: float | None = None,
        direction: str | None = None,
        start_time: time | None = None,
        units: str | None = None,
    ) -> AnalyticRun:
        run = AnalyticRun(
            project_id=project_id,
            fg_request_id=fg_request_id,
            analytic_type=analytic_type,
            threshold_c=threshold_c,
            direction=direction,
            granularity_m=granularity_m,
            start_date=start_date,
            start_time=start_time,
            filter_type=filter_type,
            # Read from the response, never assumed — see SRS C-4.
            units=units,
            stats=stats,
        )
        self._session.add(run)
        self._session.flush()
        return run

    def get_run(self, run_id: uuid.UUID) -> AnalyticRun | None:
        return self._session.get(AnalyticRun, run_id)

    def find_run(
        self,
        *,
        project_id: uuid.UUID,
        analytic_type: str,
        threshold_c: float | None = None,
    ) -> AnalyticRun | None:
        """Most recent matching run, or None.

        Used by the exceedance ladder to reuse a threshold it already has rather
        than spending a credit on it again.
        """
        stmt = select(AnalyticRun).where(
            AnalyticRun.project_id == project_id,
            AnalyticRun.analytic_type == analytic_type,
        )
        if threshold_c is None:
            stmt = stmt.where(AnalyticRun.threshold_c.is_(None))
        else:
            stmt = stmt.where(AnalyticRun.threshold_c == Decimal(str(threshold_c)))
        stmt = stmt.order_by(AnalyticRun.created_at.desc()).limit(1)
        return self._session.execute(stmt).scalar_one_or_none()

    # ── Tiles ────────────────────────────────────────────────────────────────

    def bulk_insert_tiles(
        self,
        *,
        project_id: uuid.UUID,
        analytic_run_id: uuid.UUID,
        rows: Iterable[TileRow],
    ) -> int:
        """Insert tiles in batches. Returns the number of rows written.

        Geometry is built in SQL from the tile's bounding box via
        `ST_MakeEnvelope`, which avoids serialising thousands of GeoJSON strings
        through Python.
        """
        buffer: list[dict[str, Any]] = []
        written = 0

        def flush() -> None:
            nonlocal written
            if not buffer:
                return
            stmt = pg_insert(Tile).values(
                [
                    {
                        "project_id": project_id,
                        "analytic_run_id": analytic_run_id,
                        "tile_key": item["tile_key"],
                        "geom": func.ST_MakeEnvelope(
                            item["west"], item["south"],
                            item["east"], item["north"], 4326,
                        ),
                        "centroid": func.ST_SetSRID(
                            func.ST_MakePoint(
                                (item["west"] + item["east"]) / 2.0,
                                (item["south"] + item["north"]) / 2.0,
                            ),
                            4326,
                        ),
                        "value": item["value"],
                    }
                    for item in buffer
                ]
            )
            # A re-run of the same analytic overwrites its own tiles rather than
            # failing on the unique constraint.
            stmt = stmt.on_conflict_do_update(
                index_elements=[Tile.analytic_run_id, Tile.tile_key],
                set_={"value": stmt.excluded.value},
            )
            self._session.execute(stmt)
            written += len(buffer)
            buffer.clear()

        for row in rows:
            buffer.append(
                {
                    "tile_key": row.tile_key,
                    "west": row.west,
                    "south": row.south,
                    "east": row.east,
                    "north": row.north,
                    "value": row.value,
                }
            )
            if len(buffer) >= BATCH_SIZE:
                flush()
        flush()

        log.info(
            "tiles.inserted",
            analytic_run_id=str(analytic_run_id),
            rows=written,
        )
        return written

    def tiles_for_run(self, analytic_run_id: uuid.UUID) -> list[Tile]:
        stmt = select(Tile).where(Tile.analytic_run_id == analytic_run_id)
        return list(self._session.execute(stmt).scalars())

    def tile_geojson_for_run(self, analytic_run_id: uuid.UUID) -> list[dict[str, Any]]:
        """Tiles as GeoJSON features, ready for the map layer.

        Built in SQL because `ST_AsGeoJSON` on the database side is markedly
        faster than shapely round-tripping ~7,000 polygons.
        """
        stmt = select(
            Tile.tile_key,
            Tile.value,
            func.ST_AsGeoJSON(Tile.geom),
            func.ST_X(Tile.centroid),
            func.ST_Y(Tile.centroid),
        ).where(Tile.analytic_run_id == analytic_run_id)

        features: list[dict[str, Any]] = []
        for tile_key, value, geom_json, cx, cy in self._session.execute(stmt):
            features.append(
                {
                    "type": "Feature",
                    "id": tile_key,
                    # ST_AsGeoJSON returns TEXT, not json. Passed through
                    # unparsed it reaches the response model as a string and
                    # fails validation, which is why /tiles -- the map layer --
                    # returned 500 for every project.
                    "geometry": json.loads(geom_json),
                    "properties": {
                        "tile_key": tile_key,
                        # None survives to the client as JSON null, which the
                        # map renders as the explicit no-data pattern.
                        "value": float(value) if value is not None else None,
                        "cx": float(cx),
                        "cy": float(cy),
                    },
                }
            )
        return features

    def coverage(self, analytic_run_id: uuid.UUID) -> tuple[int, int]:
        """Return (tiles_with_values, total_tiles).

        Surfaced in the UI as a data-completeness figure; a run where most tiles
        are null is a caveat the user must see, not a detail to hide.
        """
        stmt = select(
            func.count(Tile.value),
            func.count(),
        ).where(Tile.analytic_run_id == analytic_run_id)
        with_values, total = self._session.execute(stmt).one()
        return int(with_values), int(total)

    # ── Enrichment ───────────────────────────────────────────────────────────

    def upsert_features(
        self, *, project_id: uuid.UUID, rows: Sequence[dict[str, Any]]
    ) -> int:
        """Upsert tile features. Each row must carry `tile_key`."""
        if not rows:
            return 0
        written = 0
        for start in range(0, len(rows), BATCH_SIZE):
            chunk = rows[start : start + BATCH_SIZE]
            payload = [{**row, "project_id": project_id} for row in chunk]
            stmt = pg_insert(TileFeature).values(payload)
            updatable = {
                key: stmt.excluded[key]
                for key in chunk[0]
                if key not in {"tile_key", "project_id"}
            }
            if updatable:
                stmt = stmt.on_conflict_do_update(
                    index_elements=[TileFeature.project_id, TileFeature.tile_key],
                    set_=updatable,
                )
            else:
                stmt = stmt.on_conflict_do_nothing()
            self._session.execute(stmt)
            written += len(chunk)
        return written

    def upsert_exposure(
        self, *, project_id: uuid.UUID, rows: Sequence[dict[str, Any]]
    ) -> int:
        if not rows:
            return 0
        written = 0
        for start in range(0, len(rows), BATCH_SIZE):
            chunk = rows[start : start + BATCH_SIZE]
            payload = [{**row, "project_id": project_id} for row in chunk]
            stmt = pg_insert(Exposure).values(payload)
            updatable = {
                key: stmt.excluded[key]
                for key in chunk[0]
                if key not in {"tile_key", "project_id"}
            }
            if updatable:
                stmt = stmt.on_conflict_do_update(
                    index_elements=[Exposure.project_id, Exposure.tile_key],
                    set_=updatable,
                )
            else:
                stmt = stmt.on_conflict_do_nothing()
            self._session.execute(stmt)
            written += len(chunk)
        return written

    def replace_attribution(
        self, *, project_id: uuid.UUID, rows: Sequence[dict[str, Any]]
    ) -> int:
        """Replace all attributions for a project.

        Replace rather than upsert: attributions are tied to a model version, and
        mixing rows from two versions in one project would make the displayed
        drivers inconsistent with the stated model.
        """
        self._session.execute(
            delete(Attribution).where(Attribution.project_id == project_id)
        )
        if not rows:
            return 0
        for start in range(0, len(rows), BATCH_SIZE):
            chunk = rows[start : start + BATCH_SIZE]
            self._session.execute(
                pg_insert(Attribution).values(
                    [{**row, "project_id": project_id} for row in chunk]
                )
            )
        return len(rows)

    def features_for(self, project_id: uuid.UUID) -> list[TileFeature]:
        stmt = select(TileFeature).where(TileFeature.project_id == project_id)
        return list(self._session.execute(stmt).scalars())

    def exposure_for(self, project_id: uuid.UUID) -> list[Exposure]:
        stmt = select(Exposure).where(Exposure.project_id == project_id)
        return list(self._session.execute(stmt).scalars())

    def attribution_for(self, project_id: uuid.UUID) -> list[Attribution]:
        stmt = select(Attribution).where(Attribution.project_id == project_id)
        return list(self._session.execute(stmt).scalars())

    def attribution_for_tile(
        self, project_id: uuid.UUID, tile_key: str
    ) -> Attribution | None:
        return self._session.get(Attribution, (project_id, tile_key))
