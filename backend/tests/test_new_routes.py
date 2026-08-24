"""The endpoints the frontend called and the backend never served.

Eight of the frontend's twenty-two calls had no route. The response schemas all
existed; nobody had wired them up, so the Methods, Before/After, Agent Trace and
Verification pages read fixtures and nothing failed loudly enough to notice.

The tests here cover the parts that can be checked without a database. The rest
were verified against a live stack on 2026-08-22 and are recorded in the commit.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from routes.system import _limitations
from schemas.analytics import TileFeature

# ── the map layer ────────────────────────────────────────────────────────────


def test_a_string_geometry_is_rejected_by_the_tile_schema() -> None:
    """The bug that made /tiles return 500 for every project.

    `ST_AsGeoJSON` returns TEXT, and the repository passed it through unparsed.
    Pydantic rejected the string, the map layer 500'd, and because the frontend
    was still on fixtures the map looked fine the whole time.
    """
    geometry_json = json.dumps(
        {
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]],
        }
    )
    with pytest.raises(ValidationError):
        TileFeature(
            id="t",
            geometry=geometry_json,  # type: ignore[arg-type]
            properties={"tile_key": "t", "value": 1.0, "cx": 0.5, "cy": 0.5},
        )


def test_a_parsed_geometry_is_accepted(*_: object) -> None:
    feature = TileFeature(
        id="t",
        geometry={
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.0, 0.0]]],
        },
        properties={"tile_key": "t", "value": 1.0, "cx": 0.5, "cy": 0.5},
    )
    assert feature.geometry["type"] == "Polygon"


# ── the model card ───────────────────────────────────────────────────────────
#
# `limitations` is derived from the metrics rather than kept as a static list, so
# a retrain cannot leave a stale reassurance on the page.


def test_a_near_zero_r2_is_stated_as_no_transfer() -> None:
    out = _limitations({"r2": -0.009, "interval_coverage": 0.80})
    assert any("should not be presented as transferring" in line for line in out)


def test_an_overconfident_interval_is_named_as_narrower() -> None:
    """The dangerous direction has to be unmistakable. A band that is too narrow
    invites a decision it cannot support."""
    out = _limitations({"r2": 0.5, "interval_coverage": 0.28})
    assert any("NARROWER" in line for line in out)


def test_a_conservative_interval_is_named_as_wider() -> None:
    out = _limitations({"r2": 0.5, "interval_coverage": 0.93})
    assert any("wider" in line for line in out)
    assert not any("NARROWER" in line for line in out)


def test_a_calibrated_interval_raises_no_coverage_limitation() -> None:
    out = _limitations({"r2": 0.5, "interval_coverage": 0.80})
    assert not any("nominal 80%" in line for line in out)


def test_null_features_are_reported_with_their_consequence() -> None:
    """Not just that they are missing: that an intervention acting only through
    one of them is predicted to do exactly nothing."""
    out = _limitations(
        {"r2": 0.5, "interval_coverage": 0.8, "features_null": ["albedo_proxy"]}
    )
    line = next(line for line in out if "albedo_proxy" in line)
    assert "exactly zero" in line


def test_a_refusal_rate_is_reported() -> None:
    out = _limitations(
        {"r2": 0.5, "interval_coverage": 0.8, "held_out_refusal_rate": 1.0}
    )
    assert any("outside the training feature" in line for line in out)


def test_the_anomaly_target_is_disclosed() -> None:
    """A reader who assumes an absolute temperature would misread every figure."""
    out = _limitations(
        {"r2": 0.5, "interval_coverage": 0.8, "target": "anomaly_vs_district_mean_c"}
    )
    assert any("anomaly against its district mean" in line for line in out)


def test_limitations_are_never_empty() -> None:
    """The schema requires at least one entry: a model card with no stated
    limitations is a marketing claim. Clean metrics must still say something."""
    out = _limitations({"r2": 0.99, "interval_coverage": 0.80})
    assert out
    assert "suspect" in out[0]
