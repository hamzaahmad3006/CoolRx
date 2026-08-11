"""Initial CoolRx schema (SRS §13).

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-22

Additive only. There is no legacy data to preserve during the sprint, so a code
rollback is always safe without a schema rollback (SRS §24.6).

Extensions are created first: the schema depends on PostGIS, and failing here
with a clear error beats failing later on the first spatial query.
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ── projects ────────────────────────────────────────────────────────────
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=2), nullable=False),
        sa.Column(
            "aoi",
            geoalchemy2.types.Geometry(
                geometry_type="POLYGON", srid=4326, spatial_index=False
            ),
            nullable=False,
        ),
        sa.Column("area_sqmi", sa.Numeric(6, 3), nullable=False),
        sa.Column(
            "is_preset", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "area_sqmi > 0 AND area_sqmi <= 50.0", name="ck_projects_area_within_cap"
        ),
    )
    op.create_index(
        "ix_projects_aoi_gix", "projects", ["aoi"], postgresql_using="gist"
    )
    op.create_index(
        "ix_projects_preset",
        "projects",
        ["is_preset"],
        postgresql_where=sa.text("is_preset"),
    )

    # ── fg_requests ─────────────────────────────────────────────────────────
    # Cache + audit + provenance in one table. Never truncated.
    op.create_table(
        "fg_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("request_body", postgresql.JSONB(), nullable=False),
        sa.Column("activity_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("poll_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "credits_charged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("response", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "from_fixture",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        # The cache is correct by construction: a duplicate cannot exist.
        sa.UniqueConstraint("request_hash", name="uq_fg_requests_request_hash"),
    )
    op.create_index("ix_fg_requests_activity", "fg_requests", ["activity_id"])
    op.create_index(
        "ix_fg_requests_endpoint_time", "fg_requests", ["endpoint", "submitted_at"]
    )

    # ── analytic_runs ───────────────────────────────────────────────────────
    op.create_table(
        "analytic_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fg_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fg_requests.id"),
            nullable=False,
        ),
        sa.Column("analytic_type", sa.Text(), nullable=False),
        sa.Column("threshold_c", sa.Numeric(5, 2), nullable=True),
        sa.Column("direction", sa.Text(), nullable=True),
        sa.Column("granularity_m", sa.SmallInteger(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("filter_type", sa.SmallInteger(), nullable=False),
        sa.Column("units", sa.Text(), nullable=True),
        sa.Column("stats", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Mirrors the API's documented enums.
        sa.CheckConstraint(
            "granularity_m IN (60, 80, 100)", name="ck_analytic_runs_granularity"
        ),
        sa.CheckConstraint(
            "analytic_type IN ('tcm','exceedance','persistence','time_of_measure')",
            name="ck_analytic_runs_analytic_type",
        ),
        sa.CheckConstraint(
            "filter_type IN (1, 2, 3)", name="ck_analytic_runs_filter_type"
        ),
    )
    op.create_index(
        "ix_analytic_runs_lookup",
        "analytic_runs",
        ["project_id", "analytic_type", "threshold_c"],
    )

    # ── tiles ───────────────────────────────────────────────────────────────
    op.create_table(
        "tiles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "analytic_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analytic_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tile_key", sa.Text(), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="POLYGON", srid=4326, spatial_index=False
            ),
            nullable=False,
        ),
        sa.Column(
            "centroid",
            geoalchemy2.types.Geometry(
                geometry_type="POINT", srid=4326, spatial_index=False
            ),
            nullable=False,
        ),
        # NULL means missing. Never 0 — that would be a measurement.
        sa.Column("value", sa.Numeric(8, 3), nullable=True),
        sa.UniqueConstraint("analytic_run_id", "tile_key", name="uq_tiles_run_key"),
    )
    op.create_index("ix_tiles_geom_gix", "tiles", ["geom"], postgresql_using="gist")
    op.create_index(
        "ix_tiles_centroid_gix", "tiles", ["centroid"], postgresql_using="gist"
    )
    op.create_index("ix_tiles_project_key", "tiles", ["project_id", "tile_key"])

    # ── tile_features ───────────────────────────────────────────────────────
    op.create_table(
        "tile_features",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tile_key", sa.Text(), primary_key=True),
        sa.Column("canopy_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("impervious_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("building_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("water_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("grass_shrub_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("albedo_proxy", sa.Numeric(5, 3), nullable=True),
        sa.Column("openness_proxy", sa.Numeric(5, 3), nullable=True),
        sa.Column("elevation_m", sa.Numeric(7, 2), nullable=True),
        sa.Column("local_relief_m", sa.Numeric(7, 2), nullable=True),
        sa.Column("dist_to_water_m", sa.Numeric(9, 2), nullable=True),
        sa.Column("hour_utc", sa.SmallInteger(), nullable=True),
        sa.Column("doy", sa.SmallInteger(), nullable=True),
        sa.Column("district_mean_c", sa.Numeric(6, 3), nullable=True),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column(
            "enriched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ── exposure ────────────────────────────────────────────────────────────
    op.create_table(
        "exposure",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tile_key", sa.Text(), primary_key=True),
        # Dasymetric estimate — non-integer by construction, not a count.
        sa.Column("population", sa.Numeric(10, 2), nullable=True),
        sa.Column("pct_over65", sa.Numeric(5, 2), nullable=True),
        sa.Column("pct_poverty", sa.Numeric(5, 2), nullable=True),
        sa.Column("svi_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("svi_source_geoid", sa.Text(), nullable=True),
        sa.Column(
            "assets",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # ── attribution ─────────────────────────────────────────────────────────
    op.create_table(
        "attribution",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tile_key", sa.Text(), primary_key=True),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("predicted_anomaly_c", sa.Numeric(6, 3), nullable=False),
        sa.Column("ci_low_c", sa.Numeric(6, 3), nullable=False),
        sa.Column("ci_high_c", sa.Numeric(6, 3), nullable=False),
        sa.Column("shap", postgresql.JSONB(), nullable=False),
        sa.Column("top_driver", sa.Text(), nullable=False),
        # A prediction without a valid interval is unstorable.
        sa.CheckConstraint(
            "ci_low_c <= predicted_anomaly_c AND predicted_anomaly_c <= ci_high_c",
            name="ck_attribution_interval_ordered",
        ),
    )

    # ── interventions_catalog ───────────────────────────────────────────────
    op.create_table(
        "interventions_catalog",
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("unit_cost_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("delta_c_low", sa.Numeric(4, 2), nullable=False),
        sa.Column("delta_c_high", sa.Numeric(4, 2), nullable=False),
        sa.Column("lifespan_years", sa.SmallInteger(), nullable=False),
        sa.Column("maintenance_usd_yr", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "feasibility_rule",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source_citation", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "category IN ('water','green','shade','material')",
            name="ck_catalog_category",
        ),
        sa.CheckConstraint(
            "delta_c_low < delta_c_high", name="ck_catalog_delta_ordered"
        ),
        # An uncited unit cost cannot be stored (FR-013).
        sa.CheckConstraint(
            "length(trim(source_citation)) > 0", name="ck_catalog_citation_present"
        ),
    )

    # ── plans ───────────────────────────────────────────────────────────────
    op.create_table(
        "plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("budget_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column(
            "equity_lambda", sa.Numeric(4, 2), nullable=False, server_default="1.0"
        ),
        sa.Column("threshold_c", sa.Numeric(5, 2), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("total_cost_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("mean_delta_c", sa.Numeric(5, 2), nullable=False),
        sa.Column("mean_delta_c_low", sa.Numeric(5, 2), nullable=False),
        sa.Column("mean_delta_c_high", sa.Numeric(5, 2), nullable=False),
        sa.Column("heat_hours_avoided", sa.Numeric(12, 2), nullable=False),
        sa.Column("person_heat_hours_avoided", sa.Numeric(14, 2), nullable=False),
        sa.Column("people_reached", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("budget_usd > 0", name="ck_plans_budget_positive"),
        sa.CheckConstraint(
            "objective IN ('max_delta_c','max_person_heat_hours','equity_weighted')",
            name="ck_plans_objective",
        ),
        # The optimizer cannot silently overspend.
        sa.CheckConstraint(
            "total_cost_usd <= budget_usd", name="ck_plans_budget_respected"
        ),
        sa.CheckConstraint(
            "mean_delta_c_low <= mean_delta_c AND mean_delta_c <= mean_delta_c_high",
            name="ck_plans_interval_ordered",
        ),
    )
    op.create_index("ix_plans_project_time", "plans", ["project_id", "created_at"])

    # ── plan_items ──────────────────────────────────────────────────────────
    op.create_table(
        "plan_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tile_key", sa.Text(), nullable=False),
        sa.Column(
            "intervention_code",
            sa.Text(),
            sa.ForeignKey("interventions_catalog.code"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("predicted_delta_c", sa.Numeric(5, 2), nullable=False),
        sa.Column("ci_low_c", sa.Numeric(5, 2), nullable=False),
        sa.Column("ci_high_c", sa.Numeric(5, 2), nullable=False),
        sa.Column("heat_hours_avoided", sa.Numeric(10, 2), nullable=False),
        sa.Column("person_heat_hours_avoided", sa.Numeric(12, 2), nullable=False),
        sa.Column("people_affected", sa.Numeric(10, 2), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("marginal_benefit_per_usd", sa.Numeric(14, 8), nullable=False),
        # Nullable by design: the plan is valid without LLM prose.
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.CheckConstraint("quantity > 0", name="ck_plan_items_quantity_positive"),
        sa.CheckConstraint("cost_usd >= 0", name="ck_plan_items_cost_non_negative"),
        sa.CheckConstraint(
            "ci_low_c <= predicted_delta_c AND predicted_delta_c <= ci_high_c",
            name="ck_plan_items_interval_ordered",
        ),
    )
    op.create_index("ix_plan_items_plan_rank", "plan_items", ["plan_id", "rank"])

    # ── verifications ───────────────────────────────────────────────────────
    op.create_table(
        "verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("protocol", postgresql.JSONB(), nullable=False),
        sa.Column("scheduled_for", sa.Date(), nullable=False),
        sa.Column(
            "baseline_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analytic_runs.id"),
            nullable=True,
        ),
        sa.Column(
            "followup_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analytic_runs.id"),
            nullable=True,
        ),
        sa.Column("baseline_mean_c", sa.Numeric(6, 3), nullable=True),
        sa.Column("followup_mean_c", sa.Numeric(6, 3), nullable=True),
        sa.Column("control_baseline_c", sa.Numeric(6, 3), nullable=True),
        sa.Column("control_followup_c", sa.Numeric(6, 3), nullable=True),
        sa.Column("observed_delta_c", sa.Numeric(6, 3), nullable=True),
        sa.Column("predicted_delta_c", sa.Numeric(6, 3), nullable=True),
        sa.Column("within_ci", sa.Boolean(), nullable=True),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default=sa.text("'scheduled'")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ── agent_runs ──────────────────────────────────────────────────────────
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("graph_version", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("nodes", postgresql.JSONB(), nullable=False),
        sa.Column("guard_verdict", sa.Text(), nullable=False),
        sa.Column(
            "guard_violations",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "guard_verdict IN ('pass','retried','failed')",
            name="ck_agent_runs_guard_verdict",
        ),
    )

    # ── jobs ────────────────────────────────────────────────────────────────
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column(
            "progress_pct", sa.SmallInteger(), nullable=False, server_default="0"
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "kind IN ('diagnose','plan','verify','harvest')", name="ck_jobs_kind"
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','degraded')",
            name="ck_jobs_status",
        ),
        sa.CheckConstraint(
            "progress_pct >= 0 AND progress_pct <= 100", name="ck_jobs_progress_range"
        ),
    )
    op.create_index("ix_jobs_project_time", "jobs", ["project_id", "created_at"])


def downgrade() -> None:
    # Reverse dependency order.
    for table in (
        "jobs",
        "agent_runs",
        "verifications",
        "plan_items",
        "plans",
        "interventions_catalog",
        "attribution",
        "exposure",
        "tile_features",
        "tiles",
        "analytic_runs",
        "fg_requests",
        "projects",
    ):
        op.drop_table(table)
    # Extensions are intentionally left in place — other schemas may rely on them.
