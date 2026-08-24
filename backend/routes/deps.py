"""Shared route dependencies.

Controllers are constructed per request with a request-scoped session, so a
transaction never spans two requests and a failure in one cannot roll back
another's work.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from controllers.analytics import AnalyticsController
from controllers.catalog import CatalogController
from controllers.diagnose import DiagnoseController
from controllers.plan_views import PlanViewsController
from controllers.prescribe import PrescribeController
from controllers.projects import ProjectController
from core.config import Settings, get_settings
from repositories.base import get_session

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def project_controller(
    session: SessionDep, settings: SettingsDep
) -> ProjectController:
    return ProjectController(session, settings)


def diagnose_controller(
    session: SessionDep, settings: SettingsDep
) -> DiagnoseController:
    return DiagnoseController(session, settings)


def prescribe_controller(
    session: SessionDep, settings: SettingsDep
) -> PrescribeController:
    return PrescribeController(session, settings)


def analytics_controller(session: SessionDep) -> AnalyticsController:
    return AnalyticsController(session)


def plan_views_controller(session: SessionDep) -> PlanViewsController:
    return PlanViewsController(session)


def catalog_controller(session: SessionDep) -> CatalogController:
    return CatalogController(session)


ProjectControllerDep = Annotated[ProjectController, Depends(project_controller)]
DiagnoseControllerDep = Annotated[DiagnoseController, Depends(diagnose_controller)]
PrescribeControllerDep = Annotated[PrescribeController, Depends(prescribe_controller)]
AnalyticsControllerDep = Annotated[AnalyticsController, Depends(analytics_controller)]
PlanViewsControllerDep = Annotated[
    PlanViewsController, Depends(plan_views_controller)
]
CatalogControllerDep = Annotated[CatalogController, Depends(catalog_controller)]
