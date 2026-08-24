"""The shipped catalog, tested as shipped.

`test_catalog.py` covers the validator with invented rows, which is right for
testing the rules. This file tests the actual CSV that reaches a user, because two
things about it are product guarantees rather than parsing rules:

* the optimizer must be able to choose between **different kinds of intervention**,
  not just different quantities of one. A prescription engine that only ever
  answers "plant trees" is a tree recommender with extra steps;
* every number in it must be traceable. The database CHECK constraint, the loader
  and the startup gate all test that a citation *exists* — none of them can test
  that it says anything. These tests check the shape a real citation has.

Scope note: `shade` and `water` are deliberately absent. A CoolRx tile is 100 m x
100 m and a bus shelter shades about 10 m2 — it changes the radiant temperature
felt by someone under it, not the air temperature averaged over a hectare, which
is what the model trains on. Writing an air-temperature delta for a point
intervention would be inventing physics. See `data/CATALOG-RESEARCH.md`.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from optimizer.counterfactual import TileContext, check_feasibility
from repositories.catalog import read_catalog_csv

CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "interventions_catalog.csv"
)

#: Below this, a citation is a label rather than a provenance record. The shipped
#: rows run to 1,200 and 2,600 characters because they carry their assumptions.
MIN_CITATION_CHARS = 200


@pytest.fixture(scope="module")
def rows():
    parsed, violations = read_catalog_csv(CATALOG_PATH)
    assert not violations, f"shipped catalog has violations: {violations}"
    return parsed


# ── the product guarantee ────────────────────────────────────────────────────


def test_the_catalog_spans_more_than_one_category(rows) -> None:
    """The optimizer cannot make a trade-off it has no alternatives for."""
    categories = {row.category for row in rows}
    assert len(categories) >= 2, (
        f"only {categories} in the catalog — with one category the plan is a "
        f"quantity decision, not a prescription"
    )


def test_categories_differ_in_both_cost_and_effect(rows) -> None:
    """Two rows that cost the same and do the same thing are one row.

    The trade-off the optimizer exists to solve needs the options to actually
    differ: a cheap small effect against an expensive large one.
    """
    by_category = {}
    for row in rows:
        by_category.setdefault(row.category, []).append(row)

    costs = {c: min(r.unit_cost_usd for r in rs) for c, rs in by_category.items()}
    effects = {c: min(r.delta_c_low for r in rs) for c, rs in by_category.items()}
    assert len(set(costs.values())) > 1, "every category costs the same per unit"
    assert len(set(effects.values())) > 1, "every category has the same effect"


# ── provenance ───────────────────────────────────────────────────────────────


def test_every_row_cites_both_a_cost_and_an_effect(rows) -> None:
    """A row needs both halves. One sourced half and one invented half is worse
    than an empty catalog, because the citation makes the whole row look checked."""
    for row in rows:
        citation = row.source_citation.upper()
        assert "COST" in citation, f"{row.code}: no cost provenance"
        assert "EFFECT" in citation, f"{row.code}: no effect provenance"


def test_citations_are_long_enough_to_be_provenance(rows) -> None:
    for row in rows:
        assert len(row.source_citation) >= MIN_CITATION_CHARS, (
            f"{row.code}: citation is {len(row.source_citation)} chars — too short "
            f"to carry a source and its assumptions"
        )


def test_every_citation_carries_a_resolvable_reference(rows) -> None:
    """A DOI or a URL. A citation a reviewer cannot follow is an assertion."""
    for row in rows:
        citation = row.source_citation.lower()
        assert "doi:" in citation or "http" in citation, (
            f"{row.code}: citation has no DOI or URL to follow"
        )


def test_cooling_is_negative_and_ordered(rows) -> None:
    """Sign convention: cooling is negative, matching dT = counterfactual - baseline.
    A positive delta here would silently invert every prediction."""
    for row in rows:
        assert row.delta_c_low < Decimal("0"), f"{row.code}: low delta is not cooling"
        assert row.delta_c_high < Decimal("0"), f"{row.code}: high delta is not cooling"
        assert row.delta_c_low < row.delta_c_high, f"{row.code}: deltas out of order"


# ── feasibility rules the optimizer can actually read ────────────────────────


def test_feasibility_rules_use_keys_the_optimizer_supports(rows) -> None:
    """An unsupported key is not an error anywhere — it is simply never applied,
    so the rule silently does nothing and the intervention is offered on tiles it
    should have been excluded from."""
    from optimizer.counterfactual import _RULE_KEYS

    for row in rows:
        rule = row.feasibility_rule
        if not isinstance(rule, dict):
            continue
        for key in rule:
            assert key in _RULE_KEYS, (
                f"{row.code}: feasibility key {key!r} is not one the optimizer "
                f"understands, so the rule would be ignored. Supported: "
                f"{sorted(_RULE_KEYS)}"
            )


def test_a_bare_tile_admits_at_least_two_categories(rows) -> None:
    """The gate for this task: on ordinary urban ground the optimizer must have a
    genuine choice to make, not one feasible option."""
    tile = TileContext(
        tile_key="t",
        canopy_pct=8.0,
        impervious_pct=72.0,
        building_pct=30.0,
        water_pct=0.0,
        grass_shrub_pct=4.0,
        population=180.0,
    )
    feasible = {row.category for row in rows if check_feasibility(row, tile) is None}
    assert len(feasible) >= 2, (
        f"only {feasible} feasible on a normal urban tile — the plan has no "
        f"trade-off to make there"
    )


def test_a_rule_actually_excludes_where_it_should(rows) -> None:
    """The cool roof requires buildings. Open parkland should not be offered one —
    if this passes trivially the rule is not doing anything."""
    roof_rows = [r for r in rows if r.category == "material"]
    if not roof_rows:
        pytest.skip("no material row in the catalog")

    parkland = TileContext(
        tile_key="park",
        canopy_pct=55.0,
        impervious_pct=5.0,
        building_pct=0.0,
        water_pct=2.0,
        grass_shrub_pct=80.0,
    )
    assert all(check_feasibility(row, parkland) is not None for row in roof_rows), (
        "a cool roof was offered on a tile with no buildings"
    )
