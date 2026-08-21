"""Train the temperature model from recorded FortyGuard responses.

    python -m scripts.train_model --check      # report readiness, train nothing
    python -m scripts.train_model              # train, evaluate, write artefacts
    python -m scripts.train_model --allow-thin-features   # override, see below

Two preconditions decide whether training is *honest*, and both are checked
before a single booster is fit. Neither is a style rule — each one, if ignored,
produces a model whose published metrics mean something other than what the
Honesty Panel (FR-025, AC-14) claims they mean.

**1 · Grouped holdout needs more than one district.** `TrainingReport` carries
`training_districts` and `held_out_districts` because SRS §9.2 evaluates on a
*district* held out entirely. Tiles inside one district are spatially
autocorrelated: a random split leaks neighbours across the boundary and reports
an accuracy the model does not have on unseen ground. With one district there is
no honest split to make, so training stops.

**2 · The feature vector needs the land-cover and terrain providers.**
`FEATURE_ORDER` is 13 features; today only `hour_utc`, `doy` and `latitude`
resolve, because the NLCD, terrain and census providers in `geo/providers.py`
are still `UnavailableProvider`. A model fit on three features still produces
numbers — and TreeSHAP still produces attributions — but they would attribute
heat to latitude and time of day, which is not what FR-011 promises a planner.

`--allow-thin-features` exists for experimentation and stamps the resulting
metrics with `honest: false` so nothing downstream can mistake it for a
publishable model.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path
from typing import Any

import structlog

from clients.fortyguard.cache import compute_request_hash  # noqa: F401  (parity)
from clients.fortyguard.parsing import parse_heatmap
from core.config import get_settings
from geo import default_providers
from geo.providers import UnavailableProvider
from scripts._enrichment_cache import enriched_rows
from ml.features import FEATURE_ORDER
from ml.model import (
    TemperatureModel,
    TrainingReport,
    interval_coverage,
    mean_absolute_error,
    r_squared,
)

log = structlog.get_logger(__name__)

#: Features obtainable without the raster/census providers. Kept explicit so the
#: readiness report names what is missing rather than counting it.
_GEOMETRY_ONLY = frozenset({"hour_utc", "doy", "latitude"})

MIN_DISTRICTS_FOR_HOLDOUT = 2

#: Features with no citable source, as opposed to features whose provider is
#: merely unwired. Training is not blocked on these -- a model on the eleven
#: sourceable features is a real model -- but they stay in FEATURE_ORDER and are
#: named in metrics.json, because the consequence is specific and needs to be
#: visible: a feature that is null in every training row carries no information,
#: so the model makes no split on it, and a counterfactual that changes only
#: that feature predicts exactly zero cooling.
#:
#: `material` interventions act through albedo_proxy alone. Until albedo has a
#: source, a material intervention will predict no cooling at all -- not a small
#: effect, exactly zero. That is a product consequence, not a modelling detail.
KNOWN_UNSOURCED: frozenset[str] = frozenset({"albedo_proxy", "openness_proxy"})

#: Features supplied by the training assembly rather than by a provider.
#: `district_mean_c` is derived from the FortyGuard measurements themselves --
#: `apply_district_mean` does the same thing in the live pipeline -- so no
#: provider answers for it and its absence from the chain is not a gap.
DERIVED_FEATURES: frozenset[str] = frozenset({"district_mean_c"})


class NotReady(RuntimeError):
    """Training would produce a model whose metrics misrepresent it."""


def _fixture_files(fixture_dir: Path) -> list[Path]:
    return sorted(fixture_dir.glob("*.json"))


def _load_tcm_fixtures(fixture_dir: Path) -> dict[str, list[Any]]:
    """Tiles per district, from `tcm` recordings only.

    Only `tcm` carries a temperature; the exceedance and persistence rungs are
    hour counts and would poison the label column if mixed in.
    """
    by_district: dict[str, list[Any]] = defaultdict(list)

    for path in _fixture_files(fixture_dir):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("train.fixture_unreadable", path=str(path), error=str(exc))
            continue

        # Envelope shapes seen in the wild, in order of preference:
        #   {request_hash, ..., response: {map_data, stats_data}}   current
        #   {response: {data: {result: {...}}}}                     full API echo
        #   {map_data, stats_data}                                  pre-provenance
        result = payload
        response = payload.get("response")
        if isinstance(response, dict):
            data = response.get("data")
            if isinstance(data, dict) and isinstance(data.get("result"), dict):
                result = data["result"]
            else:
                result = response

        analytic = payload.get("analytic_type")
        district = str(payload.get("district") or "unknown")

        parsed = parse_heatmap(result)
        values = [t for t in parsed.tiles if t.value is not None]
        if not values:
            continue

        # Units are absent from live responses (see N-3), so `tcm` cannot be
        # identified by them. Fall back to the recorded request when present,
        # and otherwise to the physical range: hour counts are 0-24 integers,
        # temperatures in a US summer AOI are not.
        looks_like_temperature = max(v.value for v in values) > 25.0
        if analytic not in (None, "tcm") or not looks_like_temperature:
            continue

        by_district[district].extend(values)

    return dict(by_district)


def readiness(fixture_dir: Path) -> dict[str, Any]:
    """What training would and would not be able to claim, without training."""
    files = _fixture_files(fixture_dir)
    by_district = _load_tcm_fixtures(fixture_dir)

    # Probe the real chain rather than asserting what it contains. The previous
    # hardcoded answer said three features resolved long after nine did, because
    # nothing re-checked it when the providers were wired in.
    answered: set[str] = set()
    for provider in default_providers(hour_utc=22, doy=200, census_api_key=None):
        if not isinstance(provider, UnavailableProvider):
            answered |= set(provider.fields)

    answered |= DERIVED_FEATURES

    resolvable = [f for f in FEATURE_ORDER if f in answered]
    missing = [f for f in FEATURE_ORDER if f not in answered]

    return {
        "fixture_files": len(files),
        "districts": sorted(by_district),
        "district_count": len(by_district),
        "labelled_tiles": sum(len(v) for v in by_district.values()),
        "features_total": len(FEATURE_ORDER),
        "features_resolvable": resolvable,
        "features_missing": missing,
        "grouped_holdout_possible": len(by_district) >= MIN_DISTRICTS_FOR_HOLDOUT,
        "feature_vector_complete": not [
            f for f in missing if f not in KNOWN_UNSOURCED
        ],
        "features_unsourced": [f for f in missing if f in KNOWN_UNSOURCED],
    }


def _explain(state: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if not state["grouped_holdout_possible"]:
        problems.append(
            f"Grouped holdout needs {MIN_DISTRICTS_FOR_HOLDOUT}+ districts; "
            f"{state['district_count']} harvested ({', '.join(state['districts']) or 'none'}). "
            "Run: make fixtures DISTRICT=lasvegas"
        )
    if not state["feature_vector_complete"]:
        problems.append(
            f"{len([f for f in state['features_missing'] if f not in KNOWN_UNSOURCED])} "
            f"of {state['features_total']} features have a provider that is not "
            f"answering: "
            f"{', '.join(f for f in state['features_missing'] if f not in KNOWN_UNSOURCED)}. "
            "Neither has a citable source: albedo needs a per-class reflectance "
            "table, openness needs building heights."
        )
    return problems


def train(*, allow_thin: bool, model_dir: Path, fixture_dir: Path) -> int:
    settings = get_settings()
    state = readiness(fixture_dir)
    problems = _explain(state)

    print("CoolRx · temperature model training")
    print(f"  fixtures        {state['fixture_files']} file(s)")
    print(f"  districts       {state['district_count']} {state['districts']}")
    print(f"  labelled tiles  {state['labelled_tiles']}")
    print(
        f"  features        {len(state['features_resolvable'])}"
        f"/{state['features_total']} resolvable"
    )
    print()

    if problems:
        for problem in problems:
            print(f"  BLOCKED: {problem}")
        print()
        if not (allow_thin and state["labelled_tiles"]):
            print(
                "  Nothing was trained. A model fit under these conditions would\n"
                "  report metrics that overstate it, and the Honesty Panel would\n"
                "  publish them. Resolve the above, or pass --allow-thin-features\n"
                "  to produce an explicitly non-publishable artefact."
            )
            return 1
        print("  --allow-thin-features set: continuing, marking output honest=false")
        print()

    if not state["labelled_tiles"]:
        print("  No labelled tiles found in any tcm fixture. Nothing to train on.")
        return 1

    by_district = _load_tcm_fixtures(fixture_dir)
    feature_dir = fixture_dir.parent / "features"

    rows_by_district: dict[str, list[dict[str, float | None]]] = {}
    labels_by_district: dict[str, list[float]] = {}

    for district in sorted(by_district):
        tiles = by_district[district]
        print(f"  enriching {district} ({len(tiles)} labelled tiles) ...", flush=True)
        rows, labels = enriched_rows(
            district, tiles, feature_dir,
            census_api_key=settings.census_api_key,
        )
        if not rows:
            print(f"    no usable rows for {district}; skipping")
            continue
        rows_by_district[district] = rows
        labels_by_district[district] = labels
        print(f"    {len(rows)} rows")

    if len(rows_by_district) < MIN_DISTRICTS_FOR_HOLDOUT:
        print(
            f"\nOnly {len(rows_by_district)} district(s) produced usable rows. "
            f"A grouped holdout needs {MIN_DISTRICTS_FOR_HOLDOUT}."
        )
        return 1

    # Hold out one district entirely. Tiles inside a district are spatially
    # autocorrelated, so a random split leaks neighbours across the boundary and
    # reports an accuracy the model does not have on unseen ground (SRS 9.2).
    # The smallest district is held out, so the published number is the one
    # earned on the least-represented ground rather than the most.
    ordered = sorted(rows_by_district, key=lambda d: len(rows_by_district[d]))
    held_out = ordered[0]
    training = ordered[1:]

    train_rows = [r for d in training for r in rows_by_district[d]]
    train_labels = [v for d in training for v in labels_by_district[d]]
    test_rows = rows_by_district[held_out]
    test_labels = labels_by_district[held_out]

    print(f"\ntraining on  {training} ({len(train_rows)} rows)")
    print(f"  held out     {held_out} ({len(test_rows)} rows)")

    model = TemperatureModel(model_version=settings.model_version)
    model.fit(train_rows, train_labels)

    # Two different questions, and they need two different calls.
    #
    # In production the model refuses a tile whose features sit outside the
    # ranges it was trained on, and returns None rather than extrapolating. That
    # is right there: a planner must not be handed a confident number for ground
    # the model has never seen.
    #
    # For evaluation it is the wrong call. Held-out ground is a different city --
    # Las Vegas sits about 600 m up against Phoenix's 330 m, so elevation_m alone
    # puts every held-out tile outside support and refusal rate reaches 100%,
    # leaving no score at all. So the metrics are computed with enforcement off,
    # and the production refusal rate is reported next to them rather than
    # hidden by them.
    refused = sum(1 for pred in model.predict_batch(test_rows) if pred is None)
    predictions = [
        model.predict(row, enforce_support=False) for row in test_rows
    ]

    eval_labels = list(test_labels)

    refusal_rate = refused / len(test_rows) if test_rows else 0.0
    print(
        f"  production refusal rate on held-out ground  "
        f"{refusal_rate:.1%} ({refused}/{len(test_rows)})"
    )

    report = TrainingReport(
        model_version=settings.model_version,
        training_rows=len(train_rows),
        held_out_rows=len(test_rows),
        mae_c=mean_absolute_error(predictions, eval_labels),
        r2=r_squared(predictions, eval_labels),
        interval_coverage=interval_coverage(predictions, eval_labels),
        training_districts=list(training),
        held_out_districts=[held_out],
    )

    model_dir.mkdir(parents=True, exist_ok=True)
    model.save(model_dir)

    metrics = {
        "model_version": report.model_version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "honest": not problems,
        "training_rows": report.training_rows,
        "held_out_rows": report.held_out_rows,
        "held_out_refused_out_of_support": refused,
        "held_out_refusal_rate": round(refusal_rate, 4),
        "training_districts": report.training_districts,
        "held_out_districts": report.held_out_districts,
        "mae_c": round(report.mae_c, 4),
        "r2": round(report.r2, 4),
        "interval_coverage": round(report.interval_coverage, 4),
        "intervals_are_calibrated": report.intervals_are_calibrated,
        "features_used": list(FEATURE_ORDER),
        "features_populated": state["features_resolvable"],
        "features_null": state["features_missing"],
    }
    (model_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )

    print()
    print(f"  MAE                {report.mae_c:.3f} C")
    print(f"  R2                 {report.r2:.3f}")
    print(
        f"  interval coverage  {report.interval_coverage:.3f} "
        f"({'calibrated' if report.intervals_are_calibrated else 'NOT calibrated'})"
    )
    print(f"\nwritten to {model_dir}")
    if problems:
        print("  metrics.json carries honest=false")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="report readiness and exit"
    )
    parser.add_argument(
        "--allow-thin-features",
        action="store_true",
        help="train despite an incomplete feature vector; output is marked honest=false",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    fixture_dir = Path(settings.fixture_dir)
    model_dir = Path(settings.model_dir)

    if args.check:
        state = readiness(fixture_dir)
        print(json.dumps(state, indent=2))
        problems = _explain(state)
        for problem in problems:
            print(f"\nBLOCKED: {problem}", file=sys.stderr)
        return 0 if not problems else 1

    return train(
        allow_thin=args.allow_thin_features,
        model_dir=model_dir,
        fixture_dir=fixture_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
