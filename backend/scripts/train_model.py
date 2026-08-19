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
from collections import defaultdict
from pathlib import Path
from typing import Any

import structlog

from clients.fortyguard.cache import compute_request_hash  # noqa: F401  (parity)
from clients.fortyguard.parsing import parse_heatmap
from core.config import get_settings
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

    resolvable = sorted(_GEOMETRY_ONLY & set(FEATURE_ORDER))
    missing = [f for f in FEATURE_ORDER if f not in _GEOMETRY_ONLY]

    return {
        "fixture_files": len(files),
        "districts": sorted(by_district),
        "district_count": len(by_district),
        "labelled_tiles": sum(len(v) for v in by_district.values()),
        "features_total": len(FEATURE_ORDER),
        "features_resolvable": resolvable,
        "features_missing": missing,
        "grouped_holdout_possible": len(by_district) >= MIN_DISTRICTS_FOR_HOLDOUT,
        "feature_vector_complete": not missing,
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
            f"{len(state['features_missing'])} of {state['features_total']} features "
            f"cannot be resolved: {', '.join(state['features_missing'])}. "
            "These need the NLCD, terrain and census providers in geo/providers.py, "
            "which are still UnavailableProvider."
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

    print("  Training is unblocked; wire the enrichment call below and re-run.")
    print(
        "  Deliberately not implemented past this point: building the feature\n"
        "  rows requires geo.enrich over real providers. Fabricating them here\n"
        "  would be the same violation this script exists to prevent."
    )
    _ = (TemperatureModel, TrainingReport, interval_coverage,
         mean_absolute_error, r_squared, model_dir, settings)
    return 2


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
