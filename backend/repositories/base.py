"""Engine and session management.

Repositories are the only layer permitted to hold SQL (SRS §16.1). Everything
here is deliberately synchronous: RQ workers are sync, and a single session
factory shared by the API and the worker keeps the two from diverging.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on any exception."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session


def check_connectivity() -> bool:
    """Used by the readiness probe."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 — readiness must never raise
        return False


def postgis_available() -> bool:
    """Whether the PostGIS extension is installed.

    Checked explicitly because the schema depends on it and a missing extension
    is a deployment problem worth surfacing at readiness rather than on the first
    spatial query (SRS R-10).
    """
    try:
        with get_engine().connect() as connection:
            result = connection.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'postgis'")
            )
            return result.first() is not None
    except Exception:  # noqa: BLE001
        return False
