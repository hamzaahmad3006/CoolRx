"""Plan routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from schemas.plans import PlanResponse

from .deps import PrescribeControllerDep

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("/{plan_id}", response_model=PlanResponse, summary="Get a plan")
def get_plan(plan_id: uuid.UUID, controller: PrescribeControllerDep) -> PlanResponse:
    return controller.get(plan_id)
