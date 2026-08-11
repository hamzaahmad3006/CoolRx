"""SQLAlchemy table definitions — the schema from SRS §13.

This module is the single source of truth for the schema; Alembic migrations are
generated from its metadata. Constraints are declared here rather than left to
application code on purpose: several of the product's correctness rules are
enforceable in the database, and a rule the database enforces cannot be bypassed
by a new code path.

Three worth calling out:

  * ``fg_requests.request_hash`` is UNIQUE — the cache is correct by
    construction, so a duplicate submission is impossible rather than merely
    unlikely.
  * ``interventions_catalog`` requires a non-empty ``source_citation`` — an
    uncited unit cost cannot be stored, which enforces numeric grounding at the
    data layer (FR-013).
  * every interval column pair carries a CHECK that low ≤ point ≤ high, so a
    point estimate without a valid interval is unstorable (§20.3).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base. Its metadata is what Alembic compares against."""


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )


# ═════════════════════════════════════════════════════════════════════════════
# projects
# ═════════════════════════════════════════════════════════════════════════════
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    #: PostGIS geometry. WGS84 (SRID 4326) matches the GeoJSON the API exchanges.
    #: `spatial_index=False` because the GIST index is declared explicitly in
    #: __table_args__ — geoalchemy2 would otherwise create a second one and the
    #: migration would fail on a duplicate index name.
    aoi: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
        nullable=False,
    )
    area_sqmi: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)
    is_preset: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    analytic_runs: Mapped[list[AnalyticRun]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    plans: Mapped[list[Plan]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Upper bound is the Premium cap; the plan-specific limit (10 mi² on
        # Basic) is enforced in the validation layer, which knows the plan.
        CheckConstraint(
            "area_sqmi > 0 AND area_sqmi <= 50.0", name="ck_projects_area_within_cap"
        ),
        Index("ix_projects_aoi_gix", "aoi", postgresql_using="gist"),
        Index(
            "ix_projects_preset",
            "is_preset",
            postgresql_where=text("is_preset"),
        ),
    )


# ═════════════════════════════════════════════════════════════════════════════
# fg_requests — cache, audit trail and provenance backbone. Never truncated.
# ═════════════════════════════════════════════════════════════════════════════
class FgRequest(Base):
    __tablename__ = "fg_requests"

    id: Mapped[uuid.UUID] = _uuid_pk()
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    #: SHA-256 of the canonically serialised request body.
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Credentials are stripped before storage — the API key is never persisted.
    request_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: FortyGuard's own task handle. The anchor for every provenance record.
    activity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    poll_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Credits are deducted only on successful completion.
    credits_charged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_fixture: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        # Makes the cache correct by construction.
        UniqueConstraint("request_hash", name="uq_fg_requests_request_hash"),
        Index("ix_fg_requests_activity", "activity_id"),
        Index("ix_fg_requests_endpoint_time", "endpoint", "submitted_at"),
    )


# ═════════════════════════════════════════════════════════════════════════════
# analytic_runs
# ═════════════════════════════════════════════════════════════════════════════
class AnalyticRun(Base):
    __tablename__ = "analytic_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    fg_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fg_requests.id"), nullable=False
    )
    analytic_type: Mapped[str] = mapped_column(Text, nullable=False)
    threshold_c: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    direction: Mapped[str | None] = mapped_column(Text, nullable=True)
    granularity_m: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[Any | None] = mapped_column(Time, nullable=True)
    filter_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    #: Read from the API response's stats_data.units, never assumed.
    units: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="analytic_runs")

    __table_args__ = (
        # Mirrors the API's documented enums so an invalid value cannot be stored
        # even if it somehow bypassed the client.
        CheckConstraint(
            "granularity_m IN (60, 80, 100)", name="ck_analytic_runs_granularity"
        ),
        CheckConstraint(
            "analytic_type IN ('tcm','exceedance','persistence','time_of_measure')",
            name="ck_analytic_runs_analytic_type",
        ),
        CheckConstraint(
            "filter_type IN (1, 2, 3)", name="ck_analytic_runs_filter_type"
        ),
        Index(
            "ix_analytic_runs_lookup",
            "project_id",
            "analytic_type",
            "threshold_c",
        ),
    )


# ═════════════════════════════════════════════════════════════════════════════
# tiles
# ═════════════════════════════════════════════════════════════════════════════
class Tile(Base):
    __tablename__ = "tiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    analytic_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analytic_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Stable across analytics — a geohash of the tile centroid, so the same
    #: ground location keeps one key even if the API returns a different order.
    tile_key: Mapped[str] = mapped_column(Text, nullable=False)
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
        nullable=False,
    )
    centroid: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    #: NULL means missing. Never coerced to 0 — that would turn "no data" into a
    #: measurement of zero.
    value: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)

    __table_args__ = (
        UniqueConstraint("analytic_run_id", "tile_key", name="uq_tiles_run_key"),
        Index("ix_tiles_geom_gix", "geom", postgresql_using="gist"),
        Index("ix_tiles_centroid_gix", "centroid", postgresql_using="gist"),
        Index("ix_tiles_project_key", "project_id", "tile_key"),
    )


# ═════════════════════════════════════════════════════════════════════════════
# tile_features · exposure · attribution
# ═════════════════════════════════════════════════════════════════════════════
class TileFeature(Base):
    __tablename__ = "tile_features"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tile_key: Mapped[str] = mapped_column(Text, primary_key=True)

    canopy_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    impervious_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    building_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    water_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    grass_shrub_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    albedo_proxy: Mapped[float | None] = mapped_column(Numeric(5, 3))
    #: From OSM building-footprint density. NOT a true sky-view factor —
    #: no reliable free national building-height dataset exists (SRS NG-12).
    openness_proxy: Mapped[float | None] = mapped_column(Numeric(5, 3))
    elevation_m: Mapped[float | None] = mapped_column(Numeric(7, 2))
    local_relief_m: Mapped[float | None] = mapped_column(Numeric(7, 2))
    dist_to_water_m: Mapped[float | None] = mapped_column(Numeric(9, 2))
    hour_utc: Mapped[int | None] = mapped_column(SmallInteger)
    doy: Mapped[int | None] = mapped_column(SmallInteger)
    district_mean_c: Mapped[float | None] = mapped_column(Numeric(6, 3))
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    enriched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Exposure(Base):
    __tablename__ = "exposure"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tile_key: Mapped[str] = mapped_column(Text, primary_key=True)

    #: Dasymetric estimate — non-integer by construction. It is an estimate
    #: distributed from census block groups, not a count.
    population: Mapped[float | None] = mapped_column(Numeric(10, 2))
    pct_over65: Mapped[float | None] = mapped_column(Numeric(5, 2))
    pct_poverty: Mapped[float | None] = mapped_column(Numeric(5, 2))
    #: Census-TRACT resolution — coarser than a tile. Labelled as such in the UI.
    svi_score: Mapped[float | None] = mapped_column(Numeric(5, 4))
    svi_source_geoid: Mapped[str | None] = mapped_column(Text)
    assets: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class Attribution(Base):
    __tablename__ = "attribution"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tile_key: Mapped[str] = mapped_column(Text, primary_key=True)

    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_anomaly_c: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)
    ci_low_c: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)
    ci_high_c: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)
    shap: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    top_driver: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        # A prediction without a valid interval is unstorable.
        CheckConstraint(
            "ci_low_c <= predicted_anomaly_c AND predicted_anomaly_c <= ci_high_c",
            name="ck_attribution_interval_ordered",
        ),
    )


# ═════════════════════════════════════════════════════════════════════════════
# interventions_catalog
# ═════════════════════════════════════════════════════════════════════════════
class InterventionCatalogEntry(Base):
    __tablename__ = "interventions_catalog"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    #: FortyGuard's own four cooling mechanisms.
    category: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    unit_cost_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    delta_c_low: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    delta_c_high: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    lifespan_years: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    maintenance_usd_yr: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    feasibility_rule: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    #: Required and non-empty. An uncited unit cost cannot be stored.
    source_citation: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "category IN ('water','green','shade','material')",
            name="ck_catalog_category",
        ),
        CheckConstraint("delta_c_low < delta_c_high", name="ck_catalog_delta_ordered"),
        CheckConstraint(
            "length(trim(source_citation)) > 0", name="ck_catalog_citation_present"
        ),
    )


# ═════════════════════════════════════════════════════════════════════════════
# plans · plan_items
# ═════════════════════════════════════════════════════════════════════════════
class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    budget_usd: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    equity_lambda: Mapped[float] = mapped_column(
        Numeric(4, 2), nullable=False, default=1.0
    )
    threshold_c: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)

    total_cost_usd: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    mean_delta_c: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    mean_delta_c_low: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    mean_delta_c_high: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    heat_hours_avoided: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    person_heat_hours_avoided: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False
    )
    people_reached: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="plans")
    items: Mapped[list[PlanItem]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("budget_usd > 0", name="ck_plans_budget_positive"),
        CheckConstraint(
            "objective IN ('max_delta_c','max_person_heat_hours','equity_weighted')",
            name="ck_plans_objective",
        ),
        # The optimizer cannot silently overspend.
        CheckConstraint(
            "total_cost_usd <= budget_usd", name="ck_plans_budget_respected"
        ),
        CheckConstraint(
            "mean_delta_c_low <= mean_delta_c AND mean_delta_c <= mean_delta_c_high",
            name="ck_plans_interval_ordered",
        ),
        Index("ix_plans_project_time", "project_id", "created_at"),
    )


class PlanItem(Base):
    __tablename__ = "plan_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    tile_key: Mapped[str] = mapped_column(Text, nullable=False)
    intervention_code: Mapped[str] = mapped_column(
        Text, ForeignKey("interventions_catalog.code"), nullable=False
    )
    quantity: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    predicted_delta_c: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    ci_low_c: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    ci_high_c: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    heat_hours_avoided: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    person_heat_hours_avoided: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    people_affected: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Why the optimizer selected it, recorded at selection time.
    marginal_benefit_per_usd: Mapped[float] = mapped_column(
        Numeric(14, 8), nullable=False
    )
    #: LLM-authored prose. Nullable by design — the plan is valid without it,
    #: which is the structural expression of "the LLM is not load-bearing".
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan: Mapped[Plan] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_plan_items_quantity_positive"),
        CheckConstraint("cost_usd >= 0", name="ck_plan_items_cost_non_negative"),
        CheckConstraint(
            "ci_low_c <= predicted_delta_c AND predicted_delta_c <= ci_high_c",
            name="ck_plan_items_interval_ordered",
        ),
        Index("ix_plan_items_plan_rank", "plan_id", "rank"),
    )


# ═════════════════════════════════════════════════════════════════════════════
# verifications · agent_runs · jobs
# ═════════════════════════════════════════════════════════════════════════════
class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[uuid.UUID] = _uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    #: The full re-measurement recipe, including the control-tile set and the
    #: pre-registered statistical test.
    protocol: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scheduled_for: Mapped[date] = mapped_column(Date, nullable=False)
    baseline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytic_runs.id"), nullable=True
    )
    followup_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytic_runs.id"), nullable=True
    )
    baseline_mean_c: Mapped[float | None] = mapped_column(Numeric(6, 3))
    followup_mean_c: Mapped[float | None] = mapped_column(Numeric(6, 3))
    control_baseline_c: Mapped[float | None] = mapped_column(Numeric(6, 3))
    control_followup_c: Mapped[float | None] = mapped_column(Numeric(6, 3))
    #: Difference of differences — not a causal effect estimate.
    observed_delta_c: Mapped[float | None] = mapped_column(Numeric(6, 3))
    predicted_delta_c: Mapped[float | None] = mapped_column(Numeric(6, 3))
    within_ci: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'scheduled'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    graph_version: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    nodes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: pass | retried | failed — the numeric_guard verdict is part of the audit
    #: trail, not just a log line.
    guard_verdict: Mapped[str] = mapped_column(Text, nullable=False)
    guard_violations: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "guard_verdict IN ('pass','retried','failed')",
            name="ck_agent_runs_guard_verdict",
        ),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str | None] = mapped_column(Text)
    progress_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('diagnose','plan','verify','harvest')", name="ck_jobs_kind"
        ),
        CheckConstraint(
            "status IN ('queued','running','completed','failed','degraded')",
            name="ck_jobs_status",
        ),
        CheckConstraint(
            "progress_pct >= 0 AND progress_pct <= 100", name="ck_jobs_progress_range"
        ),
        Index("ix_jobs_project_time", "project_id", "created_at"),
    )
