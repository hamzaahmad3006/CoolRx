"""CoolRx API entry point.

Layering rule (SRS §16.1), enforced by review:
    routes → controllers → repositories
    routers hold no business logic · controllers hold no SQL · repositories hold
    no HTTP
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import Settings, get_settings
from middleware.correlation import CorrelationIdMiddleware
from middleware.demo_key import DemoKeyMiddleware
from middleware.errors import register_error_handlers
from middleware.rate_limit import RateLimitMiddleware
from repositories.base import check_connectivity, postgis_available, session_scope
from repositories.catalog import CatalogError, assert_catalog_ready
from routes import agent, analytics, health, jobs, plans, projects, system

log = structlog.get_logger(__name__)


def _configure_logging(settings: Settings) -> None:
    """Structured JSON logs to stdout, with secret redaction at the formatter.

    Redacting in the formatter rather than at call sites means a careless log
    statement cannot leak the API key (SRS §18.7).
    """
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )

    processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact_secrets,
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


_SECRET_KEYS = frozenset(
    {
        "api-key",
        "api_key",
        "fortyguard_api_key",
        "anthropic_api_key",
        "authorization",
        "demo_key",
        "x-demo-key",
        "password",
        "download_link",  # temporary signed URL — never log in full
    }
)


def _redact_secrets(
    _logger: object, _name: str, event_dict: structlog.typing.EventDict
) -> structlog.typing.EventDict:
    for key in list(event_dict):
        if key.lower() in _SECRET_KEYS:
            event_dict[key] = "[redacted]"
    return event_dict


def _check_catalog_at_startup(settings: Settings) -> None:
    """AC-23: refuse to serve an uncited intervention catalog.

    Two failure modes are deliberately treated differently:

    * **Database unreachable** — logged, not fatal. Crashing here turns a
      recoverable dependency outage into a container crash-loop; the readiness
      probe reports it and the orchestrator withholds traffic, which is the
      behaviour we want.
    * **Catalog present but invalid** — fatal. This is a data defect that will
      not fix itself, and the consequence is an unsourced cost figure in a
      report a city acts on.
    """
    if not check_connectivity():
        log.error(
            "startup.database_unreachable",
            detail=(
                "Catalog gate skipped — the readiness probe will report not-ready "
                "until the database is available."
            ),
        )
        return

    if not postgis_available():
        log.error(
            "startup.postgis_missing",
            detail="PostGIS extension is not installed; spatial queries will fail.",
        )

    try:
        with session_scope() as session:
            rows = assert_catalog_ready(session)
    except CatalogError as exc:
        if settings.catalog_strict:
            # Raising inside lifespan aborts startup, which is the intent.
            raise RuntimeError(f"startup aborted: {exc}") from exc
        log.warning("startup.catalog_invalid_permitted", detail=str(exc))
        return

    log.info("startup.catalog_ready", rows=rows)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging(settings)
    log.info(
        "app.startup",
        version=settings.app_version,
        env=settings.app_env,
        fixture_mode=settings.fixture_mode,
        fg_plan=settings.fg_plan,
        premium_enabled=settings.premium_available,
    )
    if settings.fixture_mode:
        log.warning(
            "app.fixture_mode",
            detail="Serving committed fixtures — no live FortyGuard calls.",
        )

    # A relaxed catalog gate in production defeats AC-23 entirely, so the
    # combination is rejected rather than warned about.
    if settings.app_env == "production" and not settings.catalog_strict:
        raise RuntimeError(
            "CATALOG_STRICT=false is not permitted in production (AC-23)."
        )

    _check_catalog_at_startup(settings)

    yield
    log.info("app.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="CoolRx API",
        version=settings.app_version,
        description=(
            "Prescription-grade urban cooling intelligence. "
            "Built on the FortyGuard Temperature API."
        ),
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # Explicit allow-list. No wildcard in production — enforced in config.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Demo-Key"],
    )
    # Order matters. Starlette applies middleware in reverse registration order, so
    # the last one added runs outermost. Correlation is therefore registered last:
    # every rejection below it — rate limit or demo key — arrives with a correlation
    # id, and one without would be untraceable in the logs.
    #
    # The demo-key check sits inside the rate limiter so an unauthenticated flood is
    # throttled before it reaches the comparison, rather than after.
    app.add_middleware(DemoKeyMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    register_error_handlers(app)

    app.include_router(health.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    app.include_router(analytics.router, prefix="/api")
    app.include_router(plans.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(system.router, prefix="/api")
    app.include_router(agent.router, prefix="/api")

    return app


app = create_app()
