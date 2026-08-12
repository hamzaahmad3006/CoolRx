"""Project and AOI routes.

No business logic here by design (SRS §16.1) — each handler unpacks the request,
calls one controller method, and returns its result. Errors propagate as domain
exceptions and are turned into the envelope by the error middleware, so no handler
contains a try/except.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from schemas.jobs import DiagnoseRequest, JobAcceptedResponse
from schemas.plans import CreatePlanRequest, ListPlansResponse
from schemas.projects import (
    CreateProjectRequest,
    ListProjectsResponse,
    ProjectResponse,
    ValidateAoiRequest,
    ValidateAoiResponse,
)

from .deps import (
    DiagnoseControllerDep,
    PrescribeControllerDep,
    ProjectControllerDep,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "/validate-aoi",
    response_model=ValidateAoiResponse,
    summary="Pre-flight an AOI without spending credits",
)
def validate_aoi(
    request: ValidateAoiRequest, controller: ProjectControllerDep
) -> ValidateAoiResponse:
    return controller.validate_aoi(request.aoi)


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project from an AOI",
)
def create_project(
    request: CreateProjectRequest, controller: ProjectControllerDep
) -> ProjectResponse:
    return controller.create(request)


@router.get("", response_model=ListProjectsResponse, summary="List projects")
def list_projects(controller: ProjectControllerDep) -> ListProjectsResponse:
    return controller.list()


@router.get("/{project_id}", response_model=ProjectResponse, summary="Get a project")
def get_project(
    project_id: uuid.UUID, controller: ProjectControllerDep
) -> ProjectResponse:
    return controller.get(project_id)


@router.post(
    "/{project_id}/diagnose",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a diagnosis",
)
def start_diagnosis(
    project_id: uuid.UUID,
    request: DiagnoseRequest,
    controller: DiagnoseControllerDep,
) -> JobAcceptedResponse:
    return controller.start(project_id, request)


@router.post(
    "/{project_id}/plans",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start plan generation",
)
def start_plan(
    project_id: uuid.UUID,
    request: CreatePlanRequest,
    controller: PrescribeControllerDep,
) -> JobAcceptedResponse:
    return controller.start(project_id, request)


@router.get(
    "/{project_id}/plans",
    response_model=ListPlansResponse,
    summary="List a project's plans",
)
def list_plans(
    project_id: uuid.UUID, controller: PrescribeControllerDep
) -> ListPlansResponse:
    return controller.list_for_project(project_id)
