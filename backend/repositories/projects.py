"""Project and AOI persistence.

The AOI arrives as GeoJSON and is stored as PostGIS geometry. The conversion
happens here and nowhere else, so there is a single place where the SRID is
asserted — a geometry stored with the wrong SRID produces silently wrong areas
and distances rather than an error.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from geoalchemy2.functions import ST_GeomFromGeoJSON
from geoalchemy2.shape import to_shape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .tables import Project

log = structlog.get_logger(__name__)

#: WGS84. The FortyGuard API, GeoJSON and MapLibre all use it, so anything else
#: entering this layer is a bug rather than a supported alternative.
SRID = 4326


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        name: str,
        city: str,
        state: str,
        aoi_geojson: dict[str, Any],
        area_sqmi: float,
        is_preset: bool = False,
    ) -> Project:
        """Persist a project.

        `area_sqmi` is passed in rather than computed in SQL on purpose: the
        geodesic area used for the plan-cap check is computed once by
        `validation.geodesic_area_sqmi`, and recomputing it with a different
        method here could accept an AOI the validator rejected.
        """
        geometry = func.ST_SetSRID(
            ST_GeomFromGeoJSON(json.dumps(aoi_geojson)), SRID
        )
        project = Project(
            name=name,
            city=city,
            state=state.upper(),
            aoi=geometry,
            area_sqmi=area_sqmi,
            is_preset=is_preset,
        )
        self._session.add(project)
        self._session.flush()
        log.info(
            "project.created",
            project_id=str(project.id),
            city=city,
            area_sqmi=area_sqmi,
        )
        return project

    def get(self, project_id: uuid.UUID) -> Project | None:
        return self._session.get(Project, project_id)

    def list_presets(self) -> list[Project]:
        stmt = (
            select(Project)
            .where(Project.is_preset.is_(True))
            .order_by(Project.city, Project.name)
        )
        return list(self._session.execute(stmt).scalars())

    def list_recent(self, limit: int = 20) -> list[Project]:
        stmt = select(Project).order_by(Project.created_at.desc()).limit(limit)
        return list(self._session.execute(stmt).scalars())

    def aoi_geojson(self, project_id: uuid.UUID) -> dict[str, Any] | None:
        """Return the AOI as a GeoJSON geometry dict."""
        stmt = select(func.ST_AsGeoJSON(Project.aoi)).where(Project.id == project_id)
        row = self._session.execute(stmt).first()
        if row is None or row[0] is None:
            return None
        parsed: dict[str, Any] = json.loads(row[0])
        return parsed

    def aoi_bounds(self, project_id: uuid.UUID) -> tuple[float, float, float, float] | None:
        """Return (west, south, east, north).

        Used to build FortyGuard requests, which take a bounding box rather than
        a polygon.
        """
        project = self.get(project_id)
        if project is None:
            return None
        shape = to_shape(project.aoi)
        west, south, east, north = shape.bounds
        return (float(west), float(south), float(east), float(north))

    def exists(self, project_id: uuid.UUID) -> bool:
        stmt = select(func.count()).select_from(Project).where(Project.id == project_id)
        return int(self._session.execute(stmt).scalar_one()) > 0
