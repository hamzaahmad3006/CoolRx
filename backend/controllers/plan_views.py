"""Plan-scoped views: counterfactual, provenance, and the verification protocol.

Three endpoints the frontend has always called and the backend has never served.

They share a controller because they share a premise: each one exists to let
somebody check the plan rather than take it on trust. The counterfactual shows
what the prediction actually is, the provenance table says where every figure
came from, and the protocol names the treated and control tiles *before* any
follow-up measurement exists — which is what stops the comparison being tuned
after the fact.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from clients.fortyguard.parsing import read_stat
from ml.counterfactual import apply_transform, transform_for_category
from ml.model import ModelNotTrained, OutOfSupport, TemperatureModel
from repositories.plans import PlanRepository
from repositories.tables import (
    AnalyticRun,
    Attribution,
    InterventionCatalogEntry,
    Plan,
    Tile,
    TileFeature,
)
from repositories.tiles import TileRepository
from schemas.analytics import TileFeature as TileFeatureSchema
from schemas.analytics import TileProperties
from schemas.common import ProvenanceRecord, ProvenanceResponse
from schemas.plans import CounterfactualResponse
from schemas.verification import VerificationProtocolResponse

log = structlog.get_logger(__name__)

#: How far ahead to schedule the follow-up measurement. A planting or a roof
#: needs a season to change anything, and a follow-up taken next week would
#: measure the weather. One year also matches the baseline's season, which
#: removes the largest confounder available to remove.
FOLLOWUP_HORIZON_DAYS = 365

#: Control tiles per treated tile. More than one because a single match makes the
#: comparison hostage to one tile's noise.
CONTROLS_PER_TREATED = 2


class PlanViewsController:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._plans = PlanRepository(session)
        self._tiles = TileRepository(session)
        from controllers.catalog import CatalogController

        self._catalog = CatalogController(session)

    # ── shared ───────────────────────────────────────────────────────────────

    def _plan_or_404(self, plan_id: uuid.UUID) -> Plan:
        plan = self._plans.get_with_items(plan_id)
        if plan is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"No plan {plan_id}"
            )
        return plan

    def _features_by_tile(self, project_id: uuid.UUID) -> dict[str, float | None]:
        """Model inputs per tile, and nothing else.

        Restricted to FEATURE_ORDER rather than every column: tile_features also
        carries timestamps, and handing a datetime to a float() conversion is how
        this first failed.
        """
        from ml.features import FEATURE_ORDER

        stmt = select(TileFeature).where(TileFeature.project_id == project_id)
        out: dict[str, dict[str, Any]] = {}
        for row in self._session.execute(stmt).scalars():
            out[row.tile_key] = {
                name: getattr(row, name, None) for name in FEATURE_ORDER
            }
        return out

    # ── counterfactual ───────────────────────────────────────────────────────

    def counterfactual(self, plan_id: uuid.UUID) -> CounterfactualResponse:
        """The predicted post-intervention field.

        Measured baseline **plus the plan item's predicted cooling**, not a fresh
        model prediction of the treated tile.

        The distinction is the whole difference between showing an intervention
        and showing model error. A model prediction of a treated tile differs
        from the measurement by two things at once: the effect of the treatment,
        and however wrong the model is about that tile. Differencing it against
        the measured field mixes the two, and on 2026-08-22 that produced a
        "predicted change" histogram that was mostly *positive* -- the swipe
        appeared to show the interventions making the district warmer, when what
        it actually showed was residual error swamping a tenth of a degree of
        cooling.

        `predicted_delta_c` carries none of that. It was computed during
        optimisation and clamped to the catalog's published range, so it is the
        cooling the plan actually claims, bounded by the citation it rests on.
        Adding it to the measurement answers the question the swipe asks: what
        does this street become if we build this.

        Both sides share one colour scale, computed across both fields. Two
        independently-scaled halves would make a tenth of a degree look dramatic.
        """
        plan = self._plan_or_404(plan_id)
        items = self._plans.items(plan_id)
        if not items:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Plan {plan_id} selected no interventions, so there is "
                f"nothing to compare against.",
            )

        run = self._latest_tcm_run(plan.project_id)
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No baseline temperature run for this project.",
            )

        geojson = {
            str(item["id"]): item
            for item in self._tiles.tile_geojson_for_run(run.id)
        }

        out: list[TileFeatureSchema] = []
        unmeasured: list[str] = []
        after_values: list[float] = []
        before_values: list[float] = []

        for shape in geojson.values():
            value = (shape["properties"] or {}).get("value")
            if value is not None:
                before_values.append(float(value))

        for item in items:
            shape = geojson.get(item.tile_key)
            if shape is None:
                unmeasured.append(item.tile_key)
                continue

            measured = (shape["properties"] or {}).get("value")
            if measured is None:
                # Treated, but never measured. Named rather than dropped: a gap
                # in the after-map needs a reason.
                unmeasured.append(item.tile_key)
                continue

            predicted_c = float(measured) + float(item.predicted_delta_c)
            after_values.append(predicted_c)

            properties = dict(shape["properties"])
            properties["value"] = round(predicted_c, 3)
            out.append(
                TileFeatureSchema(
                    id=item.tile_key,
                    geometry=shape["geometry"],
                    properties=TileProperties.model_validate(properties),
                )
            )

        if not after_values:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "No treated tile carries a baseline measurement, so no "
                    "predicted field could be produced."
                ),
            )

        combined = before_values + after_values
        return CounterfactualResponse(
            features=out,
            scale_domain=(min(combined), max(combined)),
            units=run.units,
            out_of_support_tile_keys=unmeasured,
        )

    def _model_dir(self):
        from pathlib import Path

        from core.config import get_settings

        return Path(get_settings().model_dir)

    def _activity_id_for(self, run: AnalyticRun) -> str | None:
        """The FortyGuard handle behind a run -- the provenance anchor.

        It lives on fg_requests, not on the run, because one upstream submission
        can back more than one analytic run.
        """
        from repositories.tables import FgRequest

        row = self._session.execute(
            select(FgRequest.activity_id).where(FgRequest.id == run.fg_request_id)
        ).first()
        return None if row is None else row[0]

    def _latest_tcm_run(self, project_id: uuid.UUID) -> AnalyticRun | None:
        stmt = (
            select(AnalyticRun)
            .where(
                AnalyticRun.project_id == project_id,
                AnalyticRun.analytic_type == "tcm",
            )
            .order_by(AnalyticRun.created_at.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()

    # ── provenance ───────────────────────────────────────────────────────────

    def provenance(self, plan_id: uuid.UUID) -> ProvenanceResponse:
        """Every published figure traced to where it came from.

        `value` is reproduced as a string rather than a number so this table and
        the report cannot drift apart through separate rounding.
        """
        plan = self._plan_or_404(plan_id)
        items = self._plans.items(plan_id)
        records: list[ProvenanceRecord] = []

        run = self._latest_tcm_run(plan.project_id)
        if run is not None:
            records.append(
                ProvenanceRecord(
                    figure_label="Baseline temperature field",
                    value=f"{run.analytic_type} at {run.granularity_m} m",
                    source_type="fortyguard",
                    activity_id=self._activity_id_for(run),
                    source_detail=(
                        f"FortyGuard {run.analytic_type} for "
                        f"{run.start_date} {run.start_time} UTC"
                    ),
                    retrieved_at=run.created_at,
                )
            )

        # One record per distinct intervention, carrying the citation verbatim.
        seen: set[str] = set()
        catalog = self._catalog.by_code()
        for item in items:
            if item.intervention_code in seen:
                continue
            seen.add(item.intervention_code)
            entry = catalog.get(item.intervention_code)
            if entry is None:
                continue
            records.append(
                ProvenanceRecord(
                    figure_label=f"{entry.name} — unit cost and effect",
                    value=(
                        f"${float(entry.unit_cost_usd):,.2f}/{entry.unit}, "
                        f"{float(entry.delta_c_low):+.2f} to "
                        f"{float(entry.delta_c_high):+.2f} °C"
                    ),
                    source_type="catalog",
                    activity_id=None,
                    source_detail=entry.source_citation,
                    retrieved_at=plan.created_at,
                )
            )

        attribution = self._session.execute(
            select(Attribution)
            .where(Attribution.project_id == plan.project_id)
            .limit(1)
        ).scalars().first()
        if attribution is not None:
            records.append(
                ProvenanceRecord(
                    figure_label="Predicted temperature anomaly",
                    value=f"model {attribution.model_version}",
                    source_type="model",
                    activity_id=None,
                    source_detail=(
                        f"Quantile gradient-boosted model {attribution.model_version}, "
                        f"trained on recorded FortyGuard measurements. Published "
                        f"metrics and limitations at /api/model/validation."
                    ),
                    retrieved_at=plan.created_at,
                )
            )

        records.append(
            ProvenanceRecord(
                figure_label="Plan totals",
                value=(
                    f"${float(plan.total_cost_usd):,.2f}, "
                    f"{float(plan.heat_hours_avoided):,.0f} person-heat-hours avoided"
                ),
                source_type="derived",
                activity_id=None,
                source_detail=(
                    "Summed from the selected items. Hours avoided are read off "
                    "the measured exceedance ladder at the predicted temperature, "
                    "not modelled separately."
                ),
                retrieved_at=plan.created_at,
            )
        )
        return ProvenanceResponse(records=records)

    # ── verification protocol ────────────────────────────────────────────────

    def verification_protocol(
        self, plan_id: uuid.UUID
    ) -> VerificationProtocolResponse:
        """The measurement plan, issued before any follow-up exists.

        Naming the treated and control tiles in advance is the whole point: chosen
        afterwards, controls can be picked to flatter the result.
        """
        plan = self._plan_or_404(plan_id)
        items = self._plans.items(plan_id)
        if not items:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Plan {plan_id} treats no tiles, so there is nothing to verify.",
            )

        treated = sorted({item.tile_key for item in items})
        run = self._latest_tcm_run(plan.project_id)
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No baseline temperature run for this project.",
            )

        controls = self._match_controls(plan.project_id, treated, run.id)

        scheduled = date.today() + timedelta(days=FOLLOWUP_HORIZON_DAYS)
        return VerificationProtocolResponse(
            plan_id=plan_id,
            granularity=run.granularity_m,  # type: ignore[arg-type]
            # Stored as a time, published as HH:MM.
            start_time=run.start_time.strftime("%H:%M"),
            analytic_type="tcm",
            scheduled_for=scheduled.isoformat(),
            treated_tile_keys=treated,
            control_tile_keys=controls,
            status="scheduled",
        )

    def _match_controls(
        self, project_id: uuid.UUID, treated: list[str], run_id: uuid.UUID
    ) -> list[str]:
        """Untreated tiles closest to the treated ones in baseline heat and form.

        Matched on baseline temperature and impervious cover, because those are
        what a follow-up would otherwise confound: a control that is cooler or
        greener to begin with will drift differently for reasons that have
        nothing to do with the intervention.
        """
        features = self._features_by_tile(project_id)
        baselines = {
            tile.tile_key: float(tile.value)
            for tile in self._tiles.tiles_for_run(run_id)
            if tile.value is not None
        }

        treated_set = set(treated)
        profile: list[tuple[float, float]] = []
        for key in treated:
            row = features.get(key) or {}
            impervious = row.get("impervious_pct")
            base = baselines.get(key)
            if base is not None and impervious is not None:
                profile.append((float(base), float(impervious)))
        if not profile:
            return []

        mean_base = sum(p[0] for p in profile) / len(profile)
        mean_imp = sum(p[1] for p in profile) / len(profile)

        scored: list[tuple[float, str]] = []
        for key, row in features.items():
            if key in treated_set:
                continue
            base = baselines.get(key)
            impervious = row.get("impervious_pct")
            if base is None or impervious is None:
                continue
            # Scaled so a degree and a percentage point are not summed as if
            # they were the same quantity.
            distance = (
                ((float(base) - mean_base) / 0.5) ** 2
                + ((float(impervious) - mean_imp) / 10.0) ** 2
            )
            scored.append((distance, key))

        scored.sort()
        wanted = min(len(scored), CONTROLS_PER_TREATED * len(treated))
        return sorted(key for _, key in scored[:wanted])
