"""The plan-generation pipeline.

Reads what the diagnosis persisted, scores every (tile, intervention) pair, selects
under budget, and narrates the result — in that order, because the narration node
must receive figures that are already final.

The preconditions are hard and are checked before anything is scored:

  * A completed diagnosis, or there is nothing to plan against.
  * A populated catalog, or nothing can be costed with a citation.
  * A complete exceedance ladder for at least some tiles, or a predicted ΔT cannot
    be converted into hours of danger avoided.

Each failure raises with a message naming the missing piece, because "plan
generation failed" tells a user nothing they can act on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Settings
from optimizer import (
    CatalogDeltaEstimator,
    TileContext,
    TileLadder,
    build_candidates,
    build_ladder,
    mean_delta_over_aoi,
    select_plan,
)
from repositories.jobs import JobRepository
from repositories.plans import PlanItemInput, PlanRepository, PlanTotalsInput
from repositories.tables import (
    AnalyticRun,
    Exposure,
    InterventionCatalogEntry,
    Tile,
    TileFeature,
)

log = structlog.get_logger(__name__)


class PlanPipelineError(RuntimeError):
    """Plan generation cannot proceed, with a reason the user can act on."""


#: Units applied per tile, by intervention unit. A planning convention rather than
#: a derived quantity — twelve trees is a block's worth — so it is declared here
#: and recorded on every plan item rather than being implicit in a cost.
DEFAULT_QUANTITIES: dict[str, float] = {
    "tree": 12.0,
    "m2": 400.0,
    "structure": 1.0,
    "linear_m": 60.0,
    "station": 2.0,
}


@dataclass(slots=True)
class PlanOutcome:
    plan_id: uuid.UUID
    item_count: int
    total_cost_usd: float
    infeasible_count: int
    degraded_reason: str | None = None


def run_plan_pipeline(
    *,
    session: Session,
    settings: Settings,
    job_id: uuid.UUID,
    project_id: uuid.UUID,
    budget_usd: float,
    objective: str,
    equity_lambda: float,
    threshold_c: float,
) -> PlanOutcome:
    jobs = JobRepository(session)
    plans = PlanRepository(session)

    # ── Catalog ──────────────────────────────────────────────────────────────
    jobs.advance(job_id, stage="loading_catalog", progress_pct=10)

    catalog = list(
        session.execute(select(InterventionCatalogEntry)).scalars()
    )
    if not catalog:
        raise PlanPipelineError(
            "The intervention catalog is empty, so nothing can be costed. Populate "
            "it from published cost and effect-size sources and run "
            "`python -m scripts.load_catalog`."
        )

    # ── Inputs from the diagnosis ────────────────────────────────────────────
    jobs.advance(job_id, stage="scoring_candidates", progress_pct=40)

    tiles = _tile_contexts(session, project_id)
    if not tiles:
        raise PlanPipelineError(
            "No diagnosed blocks for this project. Run a diagnosis first."
        )

    ladders = _load_ladders(session, project_id, threshold_c, settings.fg_ladder_steps)
    if not ladders:
        raise PlanPipelineError(
            "No block has a complete exceedance ladder, so predicted cooling cannot "
            "be converted into hours of dangerous heat avoided. Re-run the diagnosis "
            "with the ladder enabled."
        )

    candidates, infeasible, no_ladder = build_candidates(
        catalog=catalog,
        tiles=tiles,
        ladders=ladders,
        quantities={
            entry.code: DEFAULT_QUANTITIES.get(entry.unit, 1.0) for entry in catalog
        },
        estimator=CatalogDeltaEstimator(),
        objective=objective,  # type: ignore[arg-type]
        equity_lambda=equity_lambda,
    )

    if not candidates:
        raise PlanPipelineError(
            "No intervention is both feasible and beneficial on any block in this "
            "area. Every candidate was excluded — see the reasons on the "
            "candidates endpoint."
        )

    # ── Selection ────────────────────────────────────────────────────────────
    jobs.advance(job_id, stage="optimizing", progress_pct=70)

    result = select_plan(
        candidates=candidates,
        budget_usd=budget_usd,
        infeasible=infeasible,
        tiles_without_ladder=no_ladder,
    )
    if not result.selected:
        raise PlanPipelineError(
            f"Nothing fits a budget of ${budget_usd:,.0f}. The cheapest candidate "
            f"costs ${min(c.cost_usd for c in candidates):,.0f}."
        )

    catalog_by_code = {entry.code: entry for entry in catalog}
    mean_value, mean_low, mean_high = mean_delta_over_aoi(result, len(tiles))

    items = [
        PlanItemInput(
            tile_key=item.tile_key,
            intervention_code=item.intervention_code,
            quantity=_dec(item.quantity),
            cost_usd=_dec(item.cost_usd),
            predicted_delta_c=_dec(item.delta.value),
            ci_low_c=_dec(item.delta.low),
            ci_high_c=_dec(item.delta.high),
            heat_hours_avoided=_dec(item.hours_avoided),
            person_heat_hours_avoided=_dec(item.person_hours_avoided or 0.0),
            people_affected=_dec(item.people_affected or 0.0),
            rank=rank,
            marginal_benefit_per_usd=_dec(
                min(item.benefit_per_usd, 9_999_999.0), places="0.00000001"
            ),
            # Filled by the narration stage. Nullable by design.
            rationale=None,
        )
        for rank, item in enumerate(result.selected, start=1)
    ]

    plan = plans.create(
        project_id=project_id,
        budget_usd=_dec(budget_usd),
        objective=objective,
        equity_lambda=_dec(equity_lambda),
        threshold_c=_dec(threshold_c),
        model_version=settings.model_version,
        items=items,
        totals=PlanTotalsInput(
            mean_delta_c=_dec(mean_value),
            mean_delta_c_low=_dec(mean_low),
            mean_delta_c_high=_dec(mean_high),
            heat_hours_avoided=_dec(result.total_hours_avoided),
            person_heat_hours_avoided=_dec(result.total_person_hours_avoided),
            people_reached=_dec(result.people_reached),
        ),
    )

    # ── Narration ────────────────────────────────────────────────────────────
    jobs.advance(job_id, stage="writing_rationales", progress_pct=90)
    narration_note = _narrate(
        session=session,
        settings=settings,
        plans=plans,
        plan_id=plan.id,
        catalog_by_code=catalog_by_code,
    )

    jobs.advance(job_id, stage="finalizing", progress_pct=100)

    degraded: list[str] = []
    if no_ladder:
        degraded.append(f"{no_ladder} blocks had no complete ladder and were skipped")
    if narration_note is not None:
        degraded.append(narration_note)

    return PlanOutcome(
        plan_id=plan.id,
        item_count=len(items),
        total_cost_usd=result.total_cost_usd,
        infeasible_count=len(infeasible),
        degraded_reason="; ".join(degraded) if degraded else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Inputs
# ═════════════════════════════════════════════════════════════════════════════


def _tile_contexts(session: Session, project_id: uuid.UUID) -> dict[str, TileContext]:
    """Join features and exposure into the shape the optimizer scores against."""
    features = {
        row.tile_key: row
        for row in session.execute(
            select(TileFeature).where(TileFeature.project_id == project_id)
        ).scalars()
    }
    exposure = {
        row.tile_key: row
        for row in session.execute(
            select(Exposure).where(Exposure.project_id == project_id)
        ).scalars()
    }

    contexts: dict[str, TileContext] = {}
    for tile_key, feature in features.items():
        exposed = exposure.get(tile_key)
        contexts[tile_key] = TileContext(
            tile_key=tile_key,
            canopy_pct=_f(feature.canopy_pct),
            impervious_pct=_f(feature.impervious_pct),
            building_pct=_f(feature.building_pct),
            water_pct=_f(feature.water_pct),
            grass_shrub_pct=_f(feature.grass_shrub_pct),
            albedo_proxy=_f(feature.albedo_proxy),
            population=_f(exposed.population) if exposed else None,
            svi_score=_f(exposed.svi_score) if exposed else None,
        )
    return contexts


def _load_ladders(
    session: Session, project_id: uuid.UUID, threshold_c: float, steps: int
) -> dict[str, TileLadder]:
    """Rebuild each tile's ladder from the persisted exceedance runs."""
    by_step: dict[int, dict[str, float | None]] = {}

    for step in range(steps + 1):
        rung = Decimal(str(threshold_c + step))
        run_id = session.execute(
            select(AnalyticRun.id)
            .where(
                AnalyticRun.project_id == project_id,
                AnalyticRun.analytic_type == "exceedance",
                AnalyticRun.threshold_c == rung,
            )
            .order_by(AnalyticRun.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if run_id is None:
            log.info("plan.ladder_rung_missing", step=step, threshold=float(rung))
            return {}

        by_step[step] = {
            tile_key: (None if value is None else float(value))
            for tile_key, value in session.execute(
                select(Tile.tile_key, Tile.value).where(
                    Tile.analytic_run_id == run_id
                )
            )
        }

    tile_keys = set(by_step.get(0, {}))
    ladders: dict[str, TileLadder] = {}
    for tile_key in tile_keys:
        ladder = build_ladder(
            tile_key=tile_key,
            base_threshold_c=threshold_c,
            hours_by_step={
                step: values.get(tile_key) for step, values in by_step.items()
            },
            steps=steps,
        )
        if ladder is not None:
            ladders[tile_key] = ladder
    return ladders


def _narrate(
    *,
    session: Session,
    settings: Settings,
    plans: PlanRepository,
    plan_id: uuid.UUID,
    catalog_by_code: dict[str, InterventionCatalogEntry],
) -> str | None:
    """Attach LLM rationales, if a key is configured.

    Returns a note when narration was skipped or degraded. A missing key is not an
    error — the plan is complete without prose, which is the point of the whole
    numeric-guard design.
    """
    if settings.anthropic_api_key is None:
        return "plan text was not generated (no language-model key configured)"

    from agent.graph import PlanItemInput as NarrationItem
    from agent.graph import PlanNarrator, PlanSummaryInput
    from agent.llm import AnthropicClient

    plan = plans.get_with_items(plan_id)
    if plan is None:
        return None

    items = sorted(plan.items, key=lambda i: i.rank)
    narration_items = [
        NarrationItem(
            item_id=str(item.id),
            tile_key=item.tile_key,
            intervention_name=(
                catalog_by_code[item.intervention_code].name
                if item.intervention_code in catalog_by_code
                else item.intervention_code
            ),
            quantity=float(item.quantity),
            unit=(
                catalog_by_code[item.intervention_code].unit
                if item.intervention_code in catalog_by_code
                else "unit"
            ),
            cost_usd=float(item.cost_usd),
            predicted_delta_c=float(item.predicted_delta_c),
            ci_low_c=float(item.ci_low_c),
            ci_high_c=float(item.ci_high_c),
            heat_hours_avoided=float(item.heat_hours_avoided),
            people_affected=float(item.people_affected),
            top_driver_label="measured land cover",
            rank=item.rank,
            unit_cost_usd=(
                float(catalog_by_code[item.intervention_code].unit_cost_usd)
                if item.intervention_code in catalog_by_code
                else None
            ),
        )
        for item in items
    ]

    try:
        narrator = PlanNarrator(
            AnthropicClient(
                api_key=settings.anthropic_api_key,
                model=settings.llm_model,
                max_tokens=settings.llm_max_tokens_rationale,
            )
        )
        run = narrator.run(
            plan_id=str(plan_id),
            items=narration_items,
            summary_input=PlanSummaryInput(
                item_count=len(items),
                block_count=len({i.tile_key for i in items}),
                total_cost_usd=float(plan.total_cost_usd),
                mean_delta_c=float(plan.mean_delta_c),
                ci_low_c=float(plan.mean_delta_c_low),
                ci_high_c=float(plan.mean_delta_c_high),
                heat_hours_avoided=float(plan.heat_hours_avoided),
                people_reached=float(plan.people_reached),
            ),
        )
    except Exception as exc:  # noqa: BLE001 — narration must never fail a plan
        log.warning("plan.narration_failed", detail=str(exc))
        return "plan text could not be generated; the figures are unaffected"

    for item_id, text in run.rationales.items():
        plans.set_rationale(uuid.UUID(item_id), text)

    if run.verdict != "pass":
        dropped = sum(1 for v in run.rationales.values() if v is None)
        return (
            f"the numeric guard rejected generated text for {dropped} "
            f"{'item' if dropped == 1 else 'items'}, so it was discarded"
        )
    return None


def _f(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _dec(value: float, places: str = "0.01") -> Decimal:
    return Decimal(str(value)).quantize(Decimal(places))
