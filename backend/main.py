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
from routes import health

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
    app.add_middleware(CorrelationIdMiddleware)

    app.include_router(health.router, prefix="/api")

    return app


app = create_app()
