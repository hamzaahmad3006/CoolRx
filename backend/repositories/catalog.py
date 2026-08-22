"""Intervention catalog loading and validation (SRS §11.4, AC-23).

The catalog is the only place in CoolRx where a number is asserted rather than
computed, which is exactly why it is the most heavily policed. Every row carries
a `source_citation`, and a row without one is not a degraded row — it is a row
that cannot exist, enforced three times over:

  1. `ck_catalog_citation_present` in the database,
  2. `validate_row` here, before anything is written,
  3. `assert_catalog_ready` at startup, which refuses to boot.

The redundancy is deliberate. This is the input to every cost-effectiveness
number the product shows a city, and an uncited unit cost that reached a PDF
would be indistinguishable from a fabricated one.

This module does not contain catalog data. Per SRS §11.4 the cost and
effect-size values must be sourced by the implementer from published municipal
cost data and peer-reviewed effect-size literature; shipping plausible-looking
defaults would defeat the entire citation chain.
"""

from __future__ import annotations

import json

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .tables import InterventionCatalogEntry

log = structlog.get_logger(__name__)

VALID_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"water", "green", "shade", "material"}
)

#: Constrained rather than free-text: the UI formats a quantity per unit
#: ("12 trees", "400 m²"), so an unrecognised unit reaches the client with no
#: formatter and renders as a bare number with no dimension.
VALID_UNITS: Final[frozenset[str]] = frozenset(
    {"tree", "m2", "structure", "linear_m", "station"}
)

REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "code",
    "category",
    "name",
    "unit",
    "unit_cost_usd",
    "delta_c_low",
    "delta_c_high",
    "lifespan_years",
    "maintenance_usd_yr",
    "feasibility_rule",
    "source_citation",
)


class CatalogError(RuntimeError):
    """Raised when the catalog is missing, malformed or uncited."""


@dataclass(frozen=True, slots=True)
class RowViolation:
    row_number: int
    code: str
    field: str
    reason: str

    def __str__(self) -> str:
        return f"row {self.row_number} ({self.code or '?'}): {self.field} — {self.reason}"


@dataclass(frozen=True, slots=True)
class CatalogRow:
    code: str
    category: str
    name: str
    unit: str
    unit_cost_usd: Decimal
    delta_c_low: Decimal
    delta_c_high: Decimal
    lifespan_years: int
    maintenance_usd_yr: Decimal
    feasibility_rule: dict[str, Any]
    source_citation: str


def _decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.strip())
    except (InvalidOperation, AttributeError):
        return None


def validate_row(
    raw: dict[str, str], row_number: int
) -> tuple[CatalogRow | None, list[RowViolation]]:
    """Validate one CSV row. Returns the parsed row, or the reasons it failed."""
    code = (raw.get("code") or "").strip()
    violations: list[RowViolation] = []

    def fail(field: str, reason: str) -> None:
        violations.append(RowViolation(row_number, code, field, reason))

    if not code:
        fail("code", "must not be empty")

    category = (raw.get("category") or "").strip()
    if category not in VALID_CATEGORIES:
        fail("category", f"must be one of {sorted(VALID_CATEGORIES)}, got {category!r}")

    if not (raw.get("name") or "").strip():
        fail("name", "must not be empty")

    unit = (raw.get("unit") or "").strip()
    if unit not in VALID_UNITS:
        fail("unit", f"must be one of {sorted(VALID_UNITS)}, got {unit!r}")

    # The citation check that AC-23 turns into a boot failure.
    citation = (raw.get("source_citation") or "").strip()
    if not citation:
        fail("source_citation", "must not be empty — an uncited value cannot be used")

    cost = _decimal(raw.get("unit_cost_usd", ""))
    if cost is None:
        fail("unit_cost_usd", "must be a number")
    elif cost < 0:
        fail("unit_cost_usd", "must not be negative")

    low = _decimal(raw.get("delta_c_low", ""))
    high = _decimal(raw.get("delta_c_high", ""))
    if low is None:
        fail("delta_c_low", "must be a number")
    if high is None:
        fail("delta_c_high", "must be a number")
    if low is not None and high is not None and low >= high:
        fail("delta_c_low", f"must be strictly less than delta_c_high ({low} >= {high})")

    maintenance = _decimal(raw.get("maintenance_usd_yr", ""))
    if maintenance is None:
        fail("maintenance_usd_yr", "must be a number")
    elif maintenance < 0:
        fail("maintenance_usd_yr", "must not be negative")

    lifespan_raw = (raw.get("lifespan_years") or "").strip()
    lifespan: int | None = None
    try:
        lifespan = int(lifespan_raw)
    except ValueError:
        fail("lifespan_years", "must be an integer")
    if lifespan is not None and lifespan <= 0:
        fail("lifespan_years", "must be positive")

    if violations:
        return None, violations

    # Every value is proven present and well-typed by the checks above.
    assert cost is not None and low is not None and high is not None
    assert maintenance is not None and lifespan is not None

    # The column is documented as "JSON of tile-feature preconditions", and the
    # database column is JSONB, but this parser used to hand the raw string
    # through untouched. `check_feasibility` starts with `isinstance(rule, dict)`,
    # so a string meant every rule in the shipped catalog was silently skipped --
    # the tree row's `max_canopy_pct: 40` had never once excluded a tile, and a
    # cool roof was offered on parkland with no buildings. Nothing failed, because
    # an ignored precondition looks exactly like a satisfied one.
    rule_raw = (raw.get("feasibility_rule") or "").strip() or "{}"
    try:
        rule = json.loads(rule_raw)
    except json.JSONDecodeError as exc:
        fail("feasibility_rule", f"is not valid JSON: {exc}")
        rule = {}
    if not isinstance(rule, dict):
        fail(
            "feasibility_rule",
            f"must be a JSON object, got {type(rule).__name__}",
        )
        rule = {}

    # A key the optimizer does not recognise is not an error anywhere downstream;
    # it is simply never applied. Rejecting it here is the only place the silence
    # can be broken.
    from optimizer.counterfactual import _RULE_KEYS

    for key in rule:
        if key not in _RULE_KEYS:
            fail(
                "feasibility_rule",
                f"key {key!r} is not one the optimizer applies, so the rule would "
                f"be ignored; expected one of {sorted(_RULE_KEYS)}",
            )

    return (
        CatalogRow(
            code=code,
            category=category,
            name=raw["name"].strip(),
            unit=unit,
            unit_cost_usd=cost,
            delta_c_low=low,
            delta_c_high=high,
            lifespan_years=lifespan,
            maintenance_usd_yr=maintenance,
            feasibility_rule=rule,
            source_citation=citation,
        ),
        [],
    )


def read_catalog_csv(path: Path) -> tuple[list[CatalogRow], list[RowViolation]]:
    """Parse and validate the catalog CSV. Does not touch the database."""
    if not path.exists():
        raise CatalogError(
            f"catalog CSV not found at {path}. "
            "Populate it from published cost and effect-size sources; "
            "see the header comment in the file for the required columns."
        )

    with path.open(newline="", encoding="utf-8") as handle:
        # Lines starting with '#' are documentation, not data.
        lines = [line for line in handle if not line.lstrip().startswith("#")]

    reader = csv.DictReader(lines)
    if reader.fieldnames is None:
        raise CatalogError(f"catalog CSV at {path} has no header row")

    missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        raise CatalogError(f"catalog CSV is missing required columns: {missing}")

    rows: list[CatalogRow] = []
    violations: list[RowViolation] = []
    seen: set[str] = set()

    # Header is line 1, so data rows start at 2.
    for offset, raw in enumerate(reader, start=2):
        if not any((value or "").strip() for value in raw.values()):
            continue
        row, row_violations = validate_row(raw, offset)
        if row_violations:
            violations.extend(row_violations)
            continue
        assert row is not None
        if row.code in seen:
            violations.append(
                RowViolation(offset, row.code, "code", "duplicate code in CSV")
            )
            continue
        seen.add(row.code)
        rows.append(row)

    return rows, violations


def load_catalog(session: Session, path: Path, *, strict: bool = True) -> int:
    """Replace the catalog table contents with the CSV.

    Replace rather than upsert: a code removed from the CSV must disappear, or a
    withdrawn intervention could still be selected by the optimizer.
    """
    rows, violations = read_catalog_csv(path)

    if violations and strict:
        detail = "\n  ".join(str(v) for v in violations)
        raise CatalogError(
            f"catalog validation failed with {len(violations)} violation(s):\n  {detail}"
        )
    if violations:
        log.warning(
            "catalog.rows_rejected", count=len(violations),
            violations=[str(v) for v in violations],
        )

    if not rows and strict:
        raise CatalogError(
            f"catalog CSV at {path} contains no valid rows. "
            "The optimizer cannot run without a catalog."
        )

    session.execute(delete(InterventionCatalogEntry))
    session.add_all(
        InterventionCatalogEntry(
            code=r.code,
            category=r.category,
            name=r.name,
            unit=r.unit,
            unit_cost_usd=r.unit_cost_usd,
            delta_c_low=r.delta_c_low,
            delta_c_high=r.delta_c_high,
            lifespan_years=r.lifespan_years,
            maintenance_usd_yr=r.maintenance_usd_yr,
            feasibility_rule=r.feasibility_rule,
            source_citation=r.source_citation,
        )
        for r in rows
    )
    log.info("catalog.loaded", rows=len(rows), rejected=len(violations))
    return len(rows)


def assert_catalog_ready(session: Session) -> int:
    """AC-23 startup gate. Raises if the persisted catalog is unusable.

    Checks the database rather than the CSV, because the database is what the
    optimizer reads — a valid CSV that was never loaded is still a broken app.
    """
    total = int(session.execute(
        select(func.count()).select_from(InterventionCatalogEntry)
    ).scalar_one())
    if total == 0:
        raise CatalogError(
            "intervention catalog is empty. Run the catalog loader before serving "
            "traffic; the optimizer and every cost figure depend on it."
        )

    uncited = int(session.execute(
        select(func.count())
        .select_from(InterventionCatalogEntry)
        .where(func.length(func.trim(InterventionCatalogEntry.source_citation)) == 0)
    ).scalar_one())
    if uncited:
        raise CatalogError(
            f"{uncited} catalog row(s) have no source_citation. Refusing to start: "
            "an uncited cost or effect size must never reach a report."
        )

    log.info("catalog.ready", rows=total)
    return total
