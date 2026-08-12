"""Intervention catalog controller.

Reads only. The catalog is loaded by `scripts/load_catalog.py` and validated at
startup, so there is no write path through the API — an endpoint that could insert
a catalog row would be an endpoint that could insert an uncited unit cost, and
AC-23 exists precisely to make that impossible.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from repositories.tables import InterventionCatalogEntry
from schemas.analytics import CandidatesResponse, InterventionCatalogResponse

from .adapters import catalog_to_response
from .errors import PreconditionMissingError

log = structlog.get_logger(__name__)


class CatalogController:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self) -> list[InterventionCatalogResponse]:
        rows = list(
            self._session.execute(
                select(InterventionCatalogEntry).order_by(
                    InterventionCatalogEntry.category,
                    InterventionCatalogEntry.name,
                )
            ).scalars()
        )
        if not rows:
            # A specific, actionable message. "Empty list" would let the UI render
            # an intervention picker with nothing in it and no explanation.
            raise PreconditionMissingError(
                message=(
                    "The intervention catalog is empty. It must be populated from "
                    "published cost and effect-size sources before a plan can be "
                    "produced."
                ),
                details={"remedy": "python -m scripts.load_catalog"},
            )
        return [catalog_to_response(row) for row in rows]

    def by_code(self) -> dict[str, InterventionCatalogEntry]:
        """Code → row, for joining onto plan items."""
        rows = self._session.execute(select(InterventionCatalogEntry)).scalars()
        return {row.code: row for row in rows}

    def candidates(self) -> CandidatesResponse:
        """The catalog plus anything excluded, once an optimizer run exists.

        `infeasible` is empty until the optimizer has run for a project; it is
        populated per-plan by the prescribe controller, which knows the tile
        features the feasibility rules are evaluated against.
        """
        return CandidatesResponse(catalog=self.list(), infeasible=[])
