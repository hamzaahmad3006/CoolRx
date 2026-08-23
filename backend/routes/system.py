"""System endpoints: published model metrics and credit budget.

Both were declared in `schemas/` and consumed by the frontend, and neither had a
route. The Methods page and the credit banner were reading fixtures.

`/model/validation` matters more than its size suggests. It is the endpoint that
publishes what the model cannot do — held out by district, R2 near zero on an
unseen city, an interval that is conservative rather than calibrated. A model
card kept in a notebook is a marketing claim; one served next to the predictions
is a disclosure.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from core.config import Settings, get_settings
from schemas.system import CreditStatusResponse
from schemas.verification import ModelValidationResponse

log = structlog.get_logger(__name__)

router = APIRouter(tags=["system"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


def _limitations(metrics: dict) -> list[str]:
    """Plain-language limitations, derived from the metrics themselves.

    Written from the numbers rather than kept as a static list, so a retrain
    cannot leave a stale reassurance on the page. The schema requires at least
    one entry: a model card with no stated limitations is a marketing claim.
    """
    out: list[str] = []

    r2 = metrics.get("r2")
    if r2 is not None and r2 < 0.1:
        out.append(
            f"On a city held out of training the model explains essentially none "
            f"of the within-district variation (R2 {r2:.3f}). It is about as "
            f"accurate as predicting the district average, so it should not be "
            f"presented as transferring to a city it has never seen."
        )

    coverage = metrics.get("interval_coverage")
    if coverage is not None and abs(coverage - 0.80) > 0.05:
        direction = "wider" if coverage > 0.80 else "NARROWER"
        out.append(
            f"Prediction intervals hold {coverage:.0%} of held-out observations "
            f"against a nominal 80%, so they are {direction} than stated."
        )

    null_features = metrics.get("features_null") or []
    if null_features:
        out.append(
            f"{', '.join(null_features)} have no citable source and are null in "
            f"every row. A recommendation acting only through one of them is "
            f"predicted to have exactly zero effect, not a small one."
        )

    refusal = metrics.get("held_out_refusal_rate")
    if refusal:
        out.append(
            f"{refusal:.0%} of held-out tiles fell outside the training feature "
            f"ranges. In production those are refused rather than extrapolated."
        )

    if metrics.get("target") == "anomaly_vs_district_mean_c":
        out.append(
            "The model predicts a tile's anomaly against its district mean, not "
            "an absolute temperature. The district baseline comes from the "
            "FortyGuard measurement, not from the model."
        )

    if not out:
        out.append(
            "No limitations were derived from the published metrics, which is "
            "itself suspect: check that metrics.json is current."
        )
    return out


@router.get(
    "/model/validation",
    response_model=ModelValidationResponse,
    summary="Published model metrics and limitations",
)
def model_validation(settings: SettingsDep) -> ModelValidationResponse:
    path = Path(settings.model_dir) / "metrics.json"
    if not path.exists():
        # 503 rather than an empty body: the Methods page must not be able to
        # render a blank model card that looks like a clean bill of health.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"No published metrics at {path}. Train a model with "
                f"`python -m scripts.train_model` before serving predictions."
            ),
        )

    metrics = json.loads(path.read_text(encoding="utf-8"))
    return ModelValidationResponse(
        model_version=metrics["model_version"],
        training_tile_count=int(metrics.get("training_rows", 0)),
        training_districts=list(metrics.get("training_districts", [])),
        held_out_districts=list(metrics.get("held_out_districts", [])),
        mae_c=float(metrics["mae_c"]),
        r2=float(metrics["r2"]),
        interval_coverage=float(metrics["interval_coverage"]),
        features=list(metrics.get("features_populated", [])),
        limitations=_limitations(metrics),
    )


@router.get(
    "/credits",
    response_model=CreditStatusResponse,
    summary="FortyGuard credit budget",
)
def credits(settings: SettingsDep) -> CreditStatusResponse:
    """Remaining budget, or an honest null.

    FortyGuard publishes no balance endpoint, so `remaining` is null rather than
    an estimate (SRS C-10). `submissions_today` is our own count of chargeable
    completions, which is a lower bound that is always available.
    """
    from repositories.base import session_scope
    from repositories.fg_cache import FgCacheRepository

    submissions = 0
    try:
        with session_scope() as session:
            submissions = FgCacheRepository(session).submissions_today()
    except Exception as exc:  # noqa: BLE001 — the banner must not break on this
        log.warning("credits.count_unavailable", detail=str(exc))

    return CreditStatusResponse(
        remaining=None,
        reserve=settings.fg_credit_reserve,
        submissions_today=submissions,
        daily_cap=settings.fg_daily_submission_cap,
        live_analysis_enabled=(
            not settings.fixture_mode and submissions < settings.fg_daily_submission_cap
        ),
        mode="fixture" if settings.fixture_mode else "live",
    )
