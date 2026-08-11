"""Persistence layer.

The only layer permitted to contain SQL (SRS §16.1). Controllers call these
classes; nothing here imports a controller, a route, or an HTTP type.
"""

from __future__ import annotations

from .base import (
    check_connectivity,
    get_engine,
    get_session,
    get_session_factory,
    postgis_available,
    session_scope,
)
from .catalog import (
    CatalogError,
    CatalogRow,
    assert_catalog_ready,
    load_catalog,
    read_catalog_csv,
    validate_row,
)
from .fg_cache import FgCacheRepository, make_client_hooks
from .jobs import (
    DIAGNOSE_STAGES,
    PLAN_STAGES,
    TERMINAL_STATUSES,
    JobKind,
    JobRepository,
    JobStatus,
)
from .plans import (
    PlanIntegrityError,
    PlanItemInput,
    PlanRepository,
    PlanTotalsInput,
)
from .projects import ProjectRepository
from .tables import (
    AgentRun,
    AnalyticRun,
    Attribution,
    Base,
    Exposure,
    FgRequest,
    InterventionCatalogEntry,
    Job,
    Plan,
    PlanItem,
    Project,
    Tile,
    TileFeature,
    Verification,
)
from .tiles import TileRepository, TileRow

__all__ = [
    "DIAGNOSE_STAGES",
    "PLAN_STAGES",
    "TERMINAL_STATUSES",
    "AgentRun",
    "AnalyticRun",
    "Attribution",
    "Base",
    "CatalogError",
    "CatalogRow",
    "Exposure",
    "FgCacheRepository",
    "FgRequest",
    "InterventionCatalogEntry",
    "Job",
    "JobKind",
    "JobRepository",
    "JobStatus",
    "Plan",
    "PlanIntegrityError",
    "PlanItem",
    "PlanItemInput",
    "PlanRepository",
    "PlanTotalsInput",
    "Project",
    "ProjectRepository",
    "Tile",
    "TileFeature",
    "TileRepository",
    "TileRow",
    "Verification",
    "assert_catalog_ready",
    "check_connectivity",
    "get_engine",
    "get_session",
    "get_session_factory",
    "load_catalog",
    "make_client_hooks",
    "postgis_available",
    "read_catalog_csv",
    "session_scope",
    "validate_row",
]
