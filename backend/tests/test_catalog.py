"""Tests for catalog validation (SRS AC-23).

These assert the *rejections*. A validator that accepts everything passes a
happy-path test suite and still lets an uncited unit cost into a city's report,
so almost every test here is a negative one.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from repositories.catalog import (
    REQUIRED_COLUMNS,
    VALID_CATEGORIES,
    CatalogError,
    read_catalog_csv,
    validate_row,
)

HEADER = ",".join(REQUIRED_COLUMNS)


def _row(**overrides: str) -> dict[str, str]:
    """A row that is valid unless a test breaks it on purpose."""
    base = {
        "code": "street_tree_medium",
        "category": "green",
        "name": "Medium street tree",
        "unit": "tree",
        "unit_cost_usd": "450.00",
        "delta_c_low": "-2.50",
        "delta_c_high": "-0.40",
        "lifespan_years": "30",
        "maintenance_usd_yr": "35.00",
        "feasibility_rule": "{}",
        "source_citation": "Author, A. (2020). Title. Journal 1(1), 1-10.",
    }
    base.update(overrides)
    return base


def _reasons(raw: dict[str, str]) -> list[str]:
    _, violations = validate_row(raw, 2)
    return [f"{v.field}:{v.reason}" for v in violations]


# ── The baseline row must actually be valid ──────────────────────────────────


def test_valid_row_parses() -> None:
    row, violations = validate_row(_row(), 2)
    assert violations == []
    assert row is not None
    assert row.unit_cost_usd == Decimal("450.00")
    assert row.delta_c_low < row.delta_c_high


# ── Citation: the constraint the product depends on ─────────────────────────


@pytest.mark.parametrize("citation", ["", "   ", "\t", "\n"])
def test_empty_citation_is_rejected(citation: str) -> None:
    """An uncited value must never be storable, whitespace included."""
    reasons = _reasons(_row(source_citation=citation))
    assert any(r.startswith("source_citation:") for r in reasons)


def test_missing_citation_column_value_is_rejected() -> None:
    raw = _row()
    del raw["source_citation"]
    assert any(r.startswith("source_citation:") for r in _reasons(raw))


# ── Effect-size ordering ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("low", "high"),
    [
        ("-0.40", "-2.50"),  # inverted
        ("-1.00", "-1.00"),  # equal — the CHECK is strict
        ("0", "0"),
    ],
)
def test_delta_must_be_strictly_ordered(low: str, high: str) -> None:
    reasons = _reasons(_row(delta_c_low=low, delta_c_high=high))
    assert any("strictly less than" in r for r in reasons)


@pytest.mark.parametrize("bad", ["", "abc", "--1", "1.2.3"])
def test_non_numeric_delta_is_rejected(bad: str) -> None:
    assert any(r.startswith("delta_c_low:") for r in _reasons(_row(delta_c_low=bad)))


# ── Category, costs, lifespan ───────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["", "trees", "Green", "GREEN", "vegetation"])
def test_invalid_category_is_rejected(bad: str) -> None:
    """Categories drive the four intervention colours; a typo must not pass."""
    assert any(r.startswith("category:") for r in _reasons(_row(category=bad)))


def test_every_valid_category_is_accepted() -> None:
    for category in VALID_CATEGORIES:
        _, violations = validate_row(_row(category=category), 2)
        assert violations == [], f"{category} should be valid"


def test_negative_cost_is_rejected() -> None:
    assert any(r.startswith("unit_cost_usd:") for r in _reasons(_row(unit_cost_usd="-1")))


def test_negative_maintenance_is_rejected() -> None:
    reasons = _reasons(_row(maintenance_usd_yr="-5.00"))
    assert any(r.startswith("maintenance_usd_yr:") for r in reasons)


@pytest.mark.parametrize("bad", ["0", "-1", "", "ten", "3.5"])
def test_invalid_lifespan_is_rejected(bad: str) -> None:
    assert any(r.startswith("lifespan_years:") for r in _reasons(_row(lifespan_years=bad)))


@pytest.mark.parametrize("field", ["code", "name", "unit"])
def test_required_text_fields_must_be_present(field: str) -> None:
    assert any(r.startswith(f"{field}:") for r in _reasons(_row(**{field: "  "})))


def test_all_violations_are_reported_at_once() -> None:
    """A broken row lists every problem, so the fix is one pass not five."""
    reasons = _reasons(
        _row(code="", category="nope", unit_cost_usd="x", source_citation="")
    )
    fields = {r.split(":", 1)[0] for r in reasons}
    assert {"code", "category", "unit_cost_usd", "source_citation"} <= fields


# ── CSV level ───────────────────────────────────────────────────────────────


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="not found"):
        read_catalog_csv(tmp_path / "absent.csv")


def test_missing_columns_raise(tmp_path: Path) -> None:
    path = tmp_path / "c.csv"
    path.write_text("code,category,name\nx,green,X\n", encoding="utf-8")
    with pytest.raises(CatalogError, match="missing required columns"):
        read_catalog_csv(path)


def test_comment_lines_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "c.csv"
    row = ",".join(_row()[c] for c in REQUIRED_COLUMNS)
    path.write_text(
        f"# a comment\n#another\n{HEADER}\n{row}\n", encoding="utf-8"
    )
    rows, violations = read_catalog_csv(path)
    assert violations == []
    assert len(rows) == 1


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "c.csv"
    row = ",".join(_row()[c] for c in REQUIRED_COLUMNS)
    path.write_text(f"{HEADER}\n{row}\n\n,,,,,,,,,,\n", encoding="utf-8")
    rows, violations = read_catalog_csv(path)
    assert len(rows) == 1
    assert violations == []


def test_duplicate_codes_are_rejected(tmp_path: Path) -> None:
    """Two rows with one code would make optimizer output nondeterministic."""
    path = tmp_path / "c.csv"
    row = ",".join(_row()[c] for c in REQUIRED_COLUMNS)
    path.write_text(f"{HEADER}\n{row}\n{row}\n", encoding="utf-8")
    rows, violations = read_catalog_csv(path)
    assert len(rows) == 1
    assert any(v.reason == "duplicate code in CSV" for v in violations)


def test_violation_reports_its_row_number(tmp_path: Path) -> None:
    """The error must say which line to fix."""
    path = tmp_path / "c.csv"
    good = ",".join(_row()[c] for c in REQUIRED_COLUMNS)
    bad = ",".join(_row(code="bad_row", source_citation="")[c] for c in REQUIRED_COLUMNS)
    path.write_text(f"{HEADER}\n{good}\n{bad}\n", encoding="utf-8")
    _, violations = read_catalog_csv(path)
    assert len(violations) == 1
    assert violations[0].row_number == 3
    assert violations[0].code == "bad_row"


# ── The shipped file ────────────────────────────────────────────────────────


def test_shipped_catalog_has_the_required_header() -> None:
    """The shipped CSV has no data rows by design, but must parse.

    This is the guard on the file itself: it proves the header contract is
    intact and that the commented example never becomes a live row.
    """
    path = Path(__file__).resolve().parents[1] / "data" / "interventions_catalog.csv"
    rows, violations = read_catalog_csv(path)
    assert violations == []
    assert rows == [], (
        "the shipped catalog must stay empty — populate it from published "
        "sources, do not commit placeholder numbers"
    )
