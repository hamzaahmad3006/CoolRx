"""Assemble the Cooling Action Plan PDF from a stored plan.

The browser can already print the page, and that is not the same artefact. A
printed page is a screenshot of whatever the client happened to render; this is
generated from the database by one code path, and `report/pdf.py` refuses to emit
it at all if any headline figure lacks a provenance record.

Figures are passed as pre-formatted strings rather than floats, because the PDF
must print the same characters the screen showed. Formatting the same number
twice in two places is exactly how a report and its source come to disagree by a
rounding, months later, with no way back.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from controllers.catalog import CatalogController
from core.config import get_settings
from repositories.plans import PlanRepository
from repositories.tables import AnalyticRun, FgRequest, Project
from report.pdf import Figure, ReportData, ReportItem, build_report
from schemas.common import ESTIMATE_DISCLAIMER, VERIFICATION_CAVEAT

log = structlog.get_logger(__name__)


def _activity_id_for(session: Session, run: AnalyticRun) -> str | None:
    row = session.execute(
        select(FgRequest.activity_id).where(FgRequest.id == run.fg_request_id)
    ).first()
    return None if row is None else row[0]


def _latest_tcm_run(session: Session, project_id: uuid.UUID) -> AnalyticRun | None:
    stmt = (
        select(AnalyticRun)
        .where(
            AnalyticRun.project_id == project_id,
            AnalyticRun.analytic_type == "tcm",
        )
        .order_by(AnalyticRun.created_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def _limitations() -> list[str]:
    """The model's published limitations, from the source the API uses.

    Imported rather than restated: a PDF that carries a gentler set of caveats
    than the website is worse than one carrying none, because it looks checked.
    """
    from routes.system import _limitations as derive

    path = Path(get_settings().model_dir) / "metrics.json"
    if not path.exists():
        return [
            "No published model metrics were available when this report was "
            "generated, so its limitations could not be stated. Treat every "
            "predicted figure here as unverified."
        ]
    return derive(json.loads(path.read_text(encoding="utf-8")))


def build_plan_report(session: Session, plan_id: uuid.UUID) -> tuple[bytes, str]:
    """Render one plan to PDF bytes, with the filename it should be saved as."""
    plans = PlanRepository(session)
    plan = plans.get_with_items(plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No plan {plan_id}"
        )

    items = plans.items(plan_id)
    if not items:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Plan {plan_id} selected no interventions, so there is nothing "
                f"to report."
            ),
        )

    project = session.get(Project, plan.project_id)
    district = project.name if project is not None else str(plan.project_id)
    catalog = CatalogController(session).by_code()

    mean = (
        f"{float(plan.mean_delta_c):+.2f} C "
        f"({float(plan.mean_delta_c_low):+.2f} to "
        f"{float(plan.mean_delta_c_high):+.2f})"
    )

    # Each headline figure carries its own provenance, and the same objects go
    # into both lists. `report.pdf._validate` requires every headline label to
    # appear in provenance; building the two separately is how that check starts
    # failing for reasons nobody can see from the call site.
    headline = [
        Figure(
            label="Mean cooling across the district",
            value=mean,
            source_type="model",
            source_detail=(
                f"Quantile model {plan.model_version}, area-weighted across the "
                f"whole AOI including untreated blocks, so it is smaller than "
                f"the mean of the treated blocks. Each item's cooling is clamped "
                f"to the published range of its catalog entry. Metrics and "
                f"limitations are published at /api/model/validation."
            ),
        ),
        Figure(
            label="Dangerous hours avoided",
            value=f"{float(plan.heat_hours_avoided):,.0f} h",
            source_type="derived",
            source_detail=(
                "Read off the measured exceedance ladder at the predicted "
                "temperature, using FortyGuard's own analytic rather than a "
                "model of ours."
            ),
        ),
        Figure(
            label="People reached",
            value=f"{float(plan.people_reached):,.0f}",
            source_type="derived",
            source_detail=(
                "Dasymetric population estimate distributed from US Census block "
                "groups by built surface, summed over the treated blocks."
            ),
        ),
        Figure(
            label="Total committed",
            value=(
                f"${float(plan.total_cost_usd):,.2f} of "
                f"${float(plan.budget_usd):,.2f}"
            ),
            source_type="derived",
            source_detail="Summed from the selected items at catalog unit costs.",
        ),
    ]

    provenance = list(headline)

    run = _latest_tcm_run(session, plan.project_id)
    if run is not None:
        provenance.append(
            Figure(
                label="Baseline temperature field",
                value=f"{run.analytic_type} at {run.granularity_m} m",
                source_type="fortyguard",
                source_detail=(
                    f"FortyGuard {run.analytic_type} for {run.start_date} "
                    f"{run.start_time} UTC"
                ),
                activity_id=_activity_id_for(session, run),
            )
        )

    citations: list[str] = []
    seen: set[str] = set()
    for item in items:
        entry = catalog.get(item.intervention_code)
        if entry is None or entry.code in seen:
            continue
        seen.add(entry.code)
        # Verbatim. A summarised citation is a paraphrase of a source the reader
        # is then unable to check against.
        citations.append(entry.source_citation)
        provenance.append(
            Figure(
                label=f"{entry.name} - unit cost and effect",
                value=(
                    f"${float(entry.unit_cost_usd):,.2f}/{entry.unit}, "
                    f"{float(entry.delta_c_low):+.2f} to "
                    f"{float(entry.delta_c_high):+.2f} C"
                ),
                source_type="catalog",
                source_detail=entry.source_citation,
            )
        )

    report_items: list[ReportItem] = []
    for item in items:
        entry = catalog.get(item.intervention_code)
        unit = entry.unit if entry is not None else ""
        report_items.append(
            ReportItem(
                rank=item.rank,
                tile_key=item.tile_key,
                intervention_name=(
                    entry.name if entry is not None else item.intervention_code
                ),
                quantity=f"{float(item.quantity):,.0f} {unit}".strip(),
                cost=f"${float(item.cost_usd):,.0f}",
                predicted_delta=(
                    f"{float(item.predicted_delta_c):+.2f} C "
                    f"({float(item.ci_low_c):+.2f} to "
                    f"{float(item.ci_high_c):+.2f})"
                ),
                hours_avoided=f"{float(item.heat_hours_avoided):,.1f}",
                rationale=item.rationale,
            )
        )

    data = ReportData(
        plan_id=str(plan.id),
        district=district,
        model_version=plan.model_version,
        created_at=plan.created_at,
        summary=None,
        headline_figures=headline,
        items=report_items,
        provenance=provenance,
        citations=citations,
        limitations=_limitations(),
        estimate_disclaimer=ESTIMATE_DISCLAIMER,
        verification_caveat=VERIFICATION_CAVEAT,
        # Counted, not hidden. A plan where the guard rejected most of the
        # generated prose should say so on the page a planner signs off.
        rationales_dropped=sum(1 for item in items if item.rationale is None),
    )

    try:
        pdf = build_report(data)
    except Exception as exc:  # noqa: BLE001 — surfaced, never a blank file
        log.warning("report.build_failed", plan_id=str(plan_id), detail=str(exc))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The report could not be produced: {exc}",
        ) from exc

    log.info(
        "report.built",
        plan_id=str(plan_id),
        bytes=len(pdf),
        items=len(report_items),
        citations=len(citations),
    )
    return pdf, f"coolrx-action-plan-{plan.id}.pdf"
