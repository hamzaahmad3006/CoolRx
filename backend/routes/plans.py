"""Plan routes.

`get_plan` was the only one of these the backend served. The counterfactual,
provenance and verification endpoints were declared in `schemas/`, called by the
frontend and never routed — which is why the Before/After, Methods and
Verification pages all read fixtures.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response, status

from schemas.common import ProvenanceResponse
from schemas.plans import CounterfactualResponse, PlanResponse
from schemas.verification import (
    VerificationProtocolResponse,
    VerificationResultResponse,
    VerifyRequest,
)

from controllers.plan_report import build_plan_report

from .deps import PlanViewsControllerDep, PrescribeControllerDep, SessionDep

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("/{plan_id}", response_model=PlanResponse, summary="Get a plan")
def get_plan(plan_id: uuid.UUID, controller: PrescribeControllerDep) -> PlanResponse:
    return controller.get(plan_id)


@router.get(
    "/{plan_id}/counterfactual",
    response_model=CounterfactualResponse,
    summary="Predicted post-intervention field",
)
def counterfactual(
    plan_id: uuid.UUID, controller: PlanViewsControllerDep
) -> CounterfactualResponse:
    return controller.counterfactual(plan_id)


@router.get(
    "/{plan_id}/provenance",
    response_model=ProvenanceResponse,
    summary="Every published figure, traced to its source",
)
def provenance(
    plan_id: uuid.UUID, controller: PlanViewsControllerDep
) -> ProvenanceResponse:
    return controller.provenance(plan_id)


@router.get(
    "/{plan_id}/verification",
    response_model=VerificationProtocolResponse,
    summary="The pre-registered measurement protocol",
)
def verification_protocol(
    plan_id: uuid.UUID, controller: PlanViewsControllerDep
) -> VerificationProtocolResponse:
    return controller.verification_protocol(plan_id)


@router.get(
    "/{plan_id}/report.pdf",
    summary="The Cooling Action Plan as a PDF",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def report_pdf(plan_id: uuid.UUID, session: SessionDep) -> Response:
    """Generated from the database, not printed from the page.

    A browser print captures whatever the client rendered; this is produced by
    one code path from stored values, and `report/pdf.py` refuses to emit a
    document at all if any headline figure lacks a provenance record.

    Content-Disposition is `inline` rather than `attachment`: a judge clicking
    this should see the report, not a file in their downloads folder. The
    filename still travels with it for anyone who saves it.
    """
    pdf, filename = build_plan_report(session, plan_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post(
    "/{plan_id}/verify",
    response_model=VerificationResultResponse,
    summary="Run the difference-in-differences comparison",
)
def verify(
    plan_id: uuid.UUID,
    body: VerifyRequest,
    controller: PlanViewsControllerDep,
) -> VerificationResultResponse:
    """Compare a follow-up measurement against the pre-registered protocol.

    Returns 409 until a follow-up measurement for `followup_date` exists. That is
    the honest answer rather than a placeholder: the whole point of the protocol
    is that the comparison uses a measurement taken after the intervention was
    built, and there is no way to synthesise one. Producing a difference from the
    baseline alone would be a fabricated result wearing a statistical method's
    name.
    """
    protocol = controller.verification_protocol(plan_id)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": (
                "No follow-up measurement exists for this plan yet, so no "
                "difference-in-differences comparison can be computed."
            ),
            "scheduledFor": protocol.scheduled_for,
            "requestedFollowup": body.followup_date,
            "treatedTiles": len(protocol.treated_tile_keys),
            "controlTiles": len(protocol.control_tile_keys),
            "remedy": (
                "Re-run the tcm analytic over the same AOI, granularity and hour "
                "on or after the scheduled date, then call this endpoint again."
            ),
        },
    )
