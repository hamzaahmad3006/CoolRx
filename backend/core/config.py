"""Application configuration.

Fail-fast by design: a missing required secret raises at import time, so the
service refuses to boot rather than returning a 500 on the first user request
(SRS §26.3).

Every FortyGuard constraint that can be checked before a request is issued lives
here as a setting, because a rejected request costs nothing while a successful
one costs credits (SRS FR-002).
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production"]
FortyGuardPlan = Literal["basic", "premium", "startup"]


class Settings(BaseSettings):
    """Runtime configuration, loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_env: Environment = "development"
    app_version: str = "1.0.0"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    cors_allowed_origins: str = "http://localhost:3000"

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql+psycopg://coolrx:coolrx@localhost:5432/coolrx"
    database_pool_size: int = 5
    database_max_overflow: int = 5

    # ── Intervention catalog ─────────────────────────────────────────────────
    #: CSV the catalog is loaded from. Its cost and effect-size values must come
    #: from published sources; see data/interventions_catalog.csv for the contract.
    catalog_csv_path: str = "data/interventions_catalog.csv"

    #: AC-23: refuse to start on an uncited or malformed catalog row. Overridable
    #: only so a developer can boot the UI before sourcing the data — never in
    #: production, which is asserted at startup.
    catalog_strict: bool = True

    # ── Redis / jobs ─────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    rq_queue_name: str = "coolrx"
    job_deadline_seconds: int = 1800

    # ── FortyGuard ───────────────────────────────────────────────────────────
    fortyguard_api_key: str | None = None
    fortyguard_base_url: str = "https://api.fortyguard.com/v1"

    #: TO VERIFY on day 1 — the plan granted to hackathon participants is not
    #: documented (SRS C-8). Assume Basic; all P0 features work on it.
    fg_plan: FortyGuardPlan = "basic"

    #: 10 mi² on Basic/Startup, 50 on Premium.
    fg_max_aoi_sqmi: float = 10.0

    #: RESOLVED (SRS C-1). The official API documentation states 2019-01-01 in two
    #: places — "Supported range: 2019-01-01 through 12 hours past the current
    #: time" — and says out-of-range dates are rejected with 400. The 2021 figure
    #: in the hackathon FAQ was the outlier, and holding to it would have rejected
    #: two extra years of valid history locally, before the API ever saw it.
    fg_date_floor: date = date(2019, 1, 1)

    #: The API accepts only these three values, in metres.
    fg_granularity_options: tuple[int, ...] = (60, 80, 100)
    fg_default_granularity: int = 80
    fg_default_threshold_c: float = 35.0

    #: Exceedance-ladder steps above the threshold, for ΔT → Δhours (SRS §9.4).
    fg_ladder_steps: int = 10

    #: Forecast horizon is a hard API limit.
    fg_max_forecast_hours: int = 12

    # Polling — bounded, never an unbounded loop.
    fg_poll_initial_seconds: float = 2.0
    fg_poll_max_seconds: float = 30.0
    fg_poll_deadline_seconds: int = 600

    #: Conservative: published rate limits are unknown (SRS C-11).
    fg_max_concurrent_submissions: int = 2
    fg_breaker_failure_threshold: int = 5
    fg_breaker_cooldown_seconds: int = 120

    # Premium-only endpoints. Default OFF so a 403 changes nothing (SRS R-04).
    fg_enable_satellite: bool = False
    fg_enable_streetview: bool = False
    fg_enable_heat_intelligence: bool = False

    # Credit protection.
    fg_credit_reserve: int = 50_000
    fg_daily_submission_cap: int = 200

    # ── Fixture mode ─────────────────────────────────────────────────────────
    fixture_mode: bool = True
    fixture_dir: str = "./data/fixtures"
    #: A fixture miss raises instead of silently falling through to a live call.
    fixture_strict: bool = True

    # ── Language model ───────────────────────────────────────────────────────
    #: Which provider narrates a plan. `auto` prefers Anthropic and falls back to
    #: Groq, so setting either key is enough. `none` disables narration outright —
    #: plans still generate, they just carry no prose, which is what the whole
    #: numeric-guard design makes safe.
    llm_provider: Literal["auto", "anthropic", "groq", "none"] = "auto"

    # ── Anthropic ────────────────────────────────────────────────────────────
    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-5"
    llm_model_rationale: str = "claude-opus-5"
    llm_effort_report: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    llm_effort_rationale: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    #: NOTE: on claude-opus-5 this caps thinking AND response text together.
    llm_max_tokens_report: int = 16_000
    llm_max_tokens_rationale: int = 2_000
    llm_enable_prompt_cache: bool = True
    llm_stream_report: bool = True

    # ── Groq ─────────────────────────────────────────────────────────────────
    #: Free tier at time of writing: 30 requests/minute, 14,400/day, 6,000
    #: tokens/minute. A plan is roughly one call per item plus a summary, so a
    #: typical run fits comfortably; a very large plan can brush the token
    #: ceiling, which `GroqClient` handles by backing off rather than failing.
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    # ── ML ───────────────────────────────────────────────────────────────────
    model_dir: str = "./models"
    model_version: str = "trm-2026.08.22-a3f1"
    model_strict_version_check: bool = True

    # ── Auth / limits ────────────────────────────────────────────────────────
    #: Gate for credit-spending endpoints. Public reads need none (SRS ADR-008).
    demo_key: str | None = None
    rate_limit_write_per_hour: int = 5
    rate_limit_read_per_minute: int = 300

    # ── Observability ────────────────────────────────────────────────────────
    sentry_dsn: str | None = None
    enable_metrics_endpoint: bool = True

    # ── Derived ──────────────────────────────────────────────────────────────
    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def premium_available(self) -> bool:
        return self.fg_plan == "premium"

    @field_validator("fg_default_granularity")
    @classmethod
    def _granularity_is_supported(cls, value: int) -> int:
        if value not in (60, 80, 100):
            raise ValueError(
                f"granularity must be one of 60, 80, 100 (got {value}) — "
                "the FortyGuard API rejects any other value"
            )
        return value

    @model_validator(mode="after")
    def _check_required_secrets(self) -> Settings:
        """Refuse to boot in a configuration that cannot work.

        Live mode without an API key would fail on the first request instead of
        at startup, which is strictly worse — the failure would surface to a user
        rather than to the operator.
        """
        if not self.fixture_mode and self.fortyguard_api_key is None:
            raise ValueError(
                "FORTYGUARD_API_KEY is required when FIXTURE_MODE=false. "
                "Set the key, or run with FIXTURE_MODE=true."
            )

        if self.fg_plan == "premium" and self.fg_max_aoi_sqmi <= 10.0:
            # Not fatal, but almost certainly a misconfiguration worth surfacing.
            object.__setattr__(self, "fg_max_aoi_sqmi", 50.0)

        if self.is_production and self.demo_key is None:
            raise ValueError(
                "DEMO_KEY is required in production — it gates the endpoints "
                "that spend FortyGuard credits."
            )

        if self.is_production and "*" in self.cors_allowed_origins:
            raise ValueError("Wildcard CORS origin is not permitted in production.")

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Used as a FastAPI dependency."""
    return Settings()
