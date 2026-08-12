"""Tile prioritisation.

Deterministic aggregation over already-persisted data — no model, no catalog, no
API calls. That independence is why it lives apart from the plan search: the
priority ranking is useful the moment a diagnosis finishes, and it is the input
the optimizer later scores candidates against.

Two things are stated rather than assumed.

**Risk level is relative to this district, not absolute.** The four levels are
quartiles of hours-above-threshold *within the AOI*, so "extreme" means "worst
quarter of this district" and not a clinical or regulatory category. Assigning
absolute bands would require published health thresholds that vary by climate,
acclimatisation and population, and inventing cut-points would violate P1.

**Equity weighting is a policy choice.** `equity_weighted_phh = phh × (1 + λ·SVI)`
with λ supplied by the caller. λ=0 optimises raw heat exposure; higher values
prioritise vulnerable populations. There is no correct λ, so none is hidden.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from repositories.tables import AnalyticRun, Exposure, Tile
from schemas.analytics import TilePriorityResponse
from schemas.common import RiskLevel

log = structlog.get_logger(__name__)

#: Quartile boundaries. Index 0 → the 25th percentile, and so on.
_RISK_ORDER: tuple[RiskLevel, ...] = ("low", "moderate", "high", "extreme")


@dataclass(frozen=True, slots=True)
class _TileRow:
    tile_key: str
    exceedance_hours: float | None
    persistence_hours: float | None
    peak_hour_utc: float | None
    population: float | None
    svi_score: float | None
    longitude: float | None


def _latest_run_id(
    session: Session, project_id: uuid.UUID, analytic: str
) -> uuid.UUID | None:
    stmt = (
        select(AnalyticRun.id)
        .where(
            AnalyticRun.project_id == project_id,
            AnalyticRun.analytic_type == analytic,
        )
        .order_by(AnalyticRun.created_at.desc())
        .limit(1)
    )
    row = session.execute(stmt).first()
    return None if row is None else row[0]


def _values_for(session: Session, run_id: uuid.UUID | None) -> dict[str, float | None]:
    """tile_key → value for one analytic run."""
    if run_id is None:
        return {}
    stmt = select(Tile.tile_key, Tile.value).where(Tile.analytic_run_id == run_id)
    return {
        key: (None if value is None else float(value))
        for key, value in session.execute(stmt)
    }


def utc_hour_to_local(hour_utc: float | None, longitude: float | None) -> int | None:
    """Convert a UTC hour to approximate local solar time.

    Uses the longitude offset (15° per hour) rather than a timezone database. The
    difference matters: a planner shown a UTC peak hour would see Phoenix's
    hottest moment fall in the middle of the night. Solar time is the honest
    approximation here because the peak is a physical solar phenomenon, not a
    civil-clock one, so daylight-saving offsets would actively mislead.
    """
    if hour_utc is None or longitude is None:
        return None
    local = (round(hour_utc) + longitude / 15.0) % 24
    return int(round(local)) % 24


def _quartile_thresholds(values: list[float]) -> tuple[float, float, float]:
    """The 25th, 50th and 75th percentiles of the supplied values."""
    ordered = sorted(values)
    n = len(ordered)

    def percentile(fraction: float) -> float:
        if n == 1:
            return ordered[0]
        position = fraction * (n - 1)
        low = int(position)
        high = min(low + 1, n - 1)
        weight = position - low
        return ordered[low] * (1 - weight) + ordered[high] * weight

    return percentile(0.25), percentile(0.50), percentile(0.75)


def assign_risk_level(
    value: float | None, thresholds: tuple[float, float, float]
) -> RiskLevel:
    """Quartile band for one tile, relative to the district.

    A tile with no measurement is `low` rather than omitted, because dropping it
    would silently shrink the district; the null itself is carried in
    `exceedance_hours` so the UI can show that the band is uninformed.
    """
    if value is None:
        return "low"
    q1, q2, q3 = thresholds
    if value <= q1:
        return "low"
    if value <= q2:
        return "moderate"
    if value <= q3:
        return "high"
    return "extreme"


def rank_tiles(
    *,
    session: Session,
    project_id: uuid.UUID,
    equity_lambda: float,
    threshold_c: float,
    limit: int | None = None,
) -> list[TilePriorityResponse]:
    """Rank a project's tiles by equity-weighted person-heat-hours.

    Returns an empty list when no diagnosis has run — the caller decides whether
    that is an error, since the priorities endpoint reports it as a precondition
    while the optimizer treats it as nothing to plan against.
    """
    exceedance_run = _latest_run_id(session, project_id, "exceedance")
    persistence_run = _latest_run_id(session, project_id, "persistence")
    peak_run = _latest_run_id(session, project_id, "time_of_measure")

    exceedance = _values_for(session, exceedance_run)
    persistence = _values_for(session, persistence_run)
    peak = _values_for(session, peak_run)

    if not exceedance:
        log.info("priorities.no_exceedance_run", project_id=str(project_id))
        return []

    exposure_by_key = {
        row.tile_key: row
        for row in session.execute(
            select(Exposure).where(Exposure.project_id == project_id)
        ).scalars()
    }
    # Longitude comes from the tile centroid, computed in SQL. `tile_features`
    # stores latitude only, and ST_X on the stored point is authoritative for
    # longitude — deriving it from the AOI centre instead would shift the local
    # peak hour by up to half an hour across a wide district.
    longitude_by_key: dict[str, float] = {}
    centroid_stmt = select(Tile.tile_key, func.ST_X(Tile.centroid)).where(
        Tile.analytic_run_id == exceedance_run
    )
    for tile_key, longitude in session.execute(centroid_stmt):
        if longitude is not None:
            longitude_by_key[tile_key] = float(longitude)

    rows: list[_TileRow] = []
    for tile_key, hours in exceedance.items():
        exposure = exposure_by_key.get(tile_key)
        rows.append(
            _TileRow(
                tile_key=tile_key,
                exceedance_hours=hours,
                persistence_hours=persistence.get(tile_key),
                peak_hour_utc=peak.get(tile_key),
                population=(
                    None
                    if exposure is None or exposure.population is None
                    else float(exposure.population)
                ),
                svi_score=(
                    None
                    if exposure is None or exposure.svi_score is None
                    else float(exposure.svi_score)
                ),
                longitude=longitude_by_key.get(tile_key),
            )
        )

    measured = [row.exceedance_hours for row in rows if row.exceedance_hours is not None]
    thresholds = _quartile_thresholds(measured) if measured else (0.0, 0.0, 0.0)

    scored: list[tuple[float, TilePriorityResponse]] = []
    for row in rows:
        phh = (
            None
            if row.exceedance_hours is None or row.population is None
            else row.exceedance_hours * row.population
        )
        weighted = (
            None
            if phh is None
            else phh * (1.0 + equity_lambda * (row.svi_score or 0.0))
        )
        # Unranked tiles sort last rather than first: a tile we know nothing about
        # must not head a priority list.
        sort_key = weighted if weighted is not None else -1.0

        scored.append(
            (
                sort_key,
                TilePriorityResponse(
                    tile_key=row.tile_key,
                    rank=0,  # assigned below, once sorted
                    risk_level=assign_risk_level(row.exceedance_hours, thresholds),
                    exceedance_hours=row.exceedance_hours,
                    persistence_hours=row.persistence_hours,
                    peak_hour_local=utc_hour_to_local(row.peak_hour_utc, row.longitude),
                    population=row.population,
                    person_heat_hours=phh,
                    equity_weighted_phh=weighted,
                ),
            )
        )

    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked = [
        item.model_copy(update={"rank": index})
        for index, (_score, item) in enumerate(scored, start=1)
    ]

    log.info(
        "priorities.ranked",
        project_id=str(project_id),
        tiles=len(ranked),
        equity_lambda=equity_lambda,
        threshold_c=threshold_c,
        unranked=sum(1 for r in ranked if r.equity_weighted_phh is None),
    )
    return ranked[:limit] if limit else ranked
