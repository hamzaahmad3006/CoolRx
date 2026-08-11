"""Tests for plan-level invariants.

These run without a database. Every check they exercise happens before the
repository touches the session, which is deliberate: a plan that violates an
invariant should be rejected with an actionable message, not bounced back as an
IntegrityError naming a constraint.

Tests that need real SQL (PostGIS geometry, ON CONFLICT behaviour) require a live
PostgreSQL instance and live separately; see tests/README.md.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from repositories.plans import (
    COST_TOLERANCE_USD,
    VALID_OBJECTIVES,
    PlanIntegrityError,
    PlanItemInput,
    PlanRepository,
    PlanTotalsInput,
)

D = Decimal


class _RecordingSession:
    """Minimal stand-in that records writes without a database.

    If a test expects a rejection and the repository wrote anything, `added`
    proves it — a validation that fires after the write is not a validation.
    """

    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushes = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def add_all(self, objs: Any) -> None:
        self.added.extend(objs)

    def flush(self) -> None:
        self.flushes += 1


def _item(**overrides: object) -> PlanItemInput:
    base: dict[str, Any] = {
        "tile_key": "9q8yy",
        "intervention_code": "street_tree_medium",
        "quantity": D("12"),
        "cost_usd": D("5400.00"),
        "predicted_delta_c": D("-1.90"),
        "ci_low_c": D("-2.60"),
        "ci_high_c": D("-1.20"),
        "heat_hours_avoided": D("310.00"),
        "person_heat_hours_avoided": D("18400.00"),
        "people_affected": D("640.00"),
        "rank": 1,
        "marginal_benefit_per_usd": D("3.40740741"),
    }
    base.update(overrides)
    return PlanItemInput(**base)


def _totals(**overrides: object) -> PlanTotalsInput:
    base: dict[str, Any] = {
        "mean_delta_c": D("-1.90"),
        "mean_delta_c_low": D("-2.60"),
        "mean_delta_c_high": D("-1.20"),
        "heat_hours_avoided": D("310.00"),
        "person_heat_hours_avoided": D("18400.00"),
        "people_reached": D("640.00"),
    }
    base.update(overrides)
    return PlanTotalsInput(**base)


def _create(
    session: _RecordingSession, **overrides: object
) -> object:
    repo = PlanRepository(session)  # type: ignore[arg-type]
    kwargs: dict[str, Any] = {
        "project_id": uuid.uuid4(),
        "budget_usd": D("10000.00"),
        "objective": "equity_weighted",
        "equity_lambda": D("1.00"),
        "threshold_c": D("35.00"),
        "model_version": "lgbm-2026.08.1",
        "items": [_item()],
        "totals": _totals(),
    }
    kwargs.update(overrides)
    return repo.create(**kwargs)


# ── Item-level: the interval must contain the estimate ──────────────────────


def test_valid_item_constructs() -> None:
    item = _item()
    assert item.ci_low_c <= item.predicted_delta_c <= item.ci_high_c


@pytest.mark.parametrize(
    ("low", "point", "high"),
    [
        ("-2.60", "-3.00", "-1.20"),  # below the interval
        ("-2.60", "-0.50", "-1.20"),  # above the interval
        ("-1.20", "-1.90", "-2.60"),  # bounds inverted
    ],
)
def test_item_interval_must_contain_estimate(low: str, point: str, high: str) -> None:
    """A point estimate outside its own interval is not a degraded value.

    It is incoherent, and it must be impossible to construct.
    """
    with pytest.raises(PlanIntegrityError, match="does not contain"):
        _item(ci_low_c=D(low), predicted_delta_c=D(point), ci_high_c=D(high))


def test_item_interval_endpoints_are_inclusive() -> None:
    """A prediction sitting exactly on a bound is legitimate."""
    assert _item(predicted_delta_c=D("-2.60")).predicted_delta_c == D("-2.60")
    assert _item(predicted_delta_c=D("-1.20")).predicted_delta_c == D("-1.20")


@pytest.mark.parametrize("quantity", ["0", "-1", "-0.01"])
def test_item_quantity_must_be_positive(quantity: str) -> None:
    with pytest.raises(PlanIntegrityError, match="quantity must be positive"):
        _item(quantity=D(quantity))


def test_item_cost_must_not_be_negative() -> None:
    with pytest.raises(PlanIntegrityError, match="must not be negative"):
        _item(cost_usd=D("-0.01"))


def test_item_cost_may_be_zero() -> None:
    """A zero-cost item is legitimate — e.g. a policy change with no capital cost."""
    assert _item(cost_usd=D("0")).cost_usd == D("0")


# ── Plan-level: budget is a hard ceiling ────────────────────────────────────


def test_over_budget_plan_is_rejected_before_any_write() -> None:
    """The strongest guarantee in this module: overspend cannot be persisted."""
    session = _RecordingSession()
    items = [_item(cost_usd=D("9000.00"), rank=1), _item(cost_usd=D("2000.00"), rank=2)]
    with pytest.raises(PlanIntegrityError, match="exceeds budget"):
        _create(session, budget_usd=D("10000.00"), items=items)
    assert session.added == [], "nothing may be written when the plan is rejected"


def test_plan_exactly_at_budget_is_accepted() -> None:
    session = _RecordingSession()
    _create(
        session,
        budget_usd=D("5400.00"),
        items=[_item(cost_usd=D("5400.00"))],
    )
    assert len(session.added) == 2  # the plan and its one item


def test_total_cost_is_recomputed_from_items() -> None:
    """The stored total is derived, so a caller cannot understate the spend."""
    session = _RecordingSession()
    items = [
        _item(cost_usd=D("1000.00"), rank=1),
        _item(cost_usd=D("2500.50"), rank=2),
        _item(cost_usd=D("400.25"), rank=3),
    ]
    plan = _create(session, budget_usd=D("10000.00"), items=items)
    assert getattr(plan, "total_cost_usd") == D("3900.75")


@pytest.mark.parametrize("budget", ["0", "-1", "-1000.00"])
def test_non_positive_budget_is_rejected(budget: str) -> None:
    with pytest.raises(PlanIntegrityError, match="budget must be positive"):
        _create(_RecordingSession(), budget_usd=D(budget))


# ── Plan-level: objective, items, ranks, interval ───────────────────────────


@pytest.mark.parametrize("objective", ["", "max_delta", "MAX_DELTA_C", "cheapest"])
def test_unknown_objective_is_rejected(objective: str) -> None:
    with pytest.raises(PlanIntegrityError, match="unknown objective"):
        _create(_RecordingSession(), objective=objective)


def test_every_valid_objective_is_accepted() -> None:
    for objective in VALID_OBJECTIVES:
        session = _RecordingSession()
        _create(session, objective=objective)
        assert session.added, f"{objective} should be accepted"


def test_empty_plan_is_rejected() -> None:
    """An empty plan would claim a benefit with nothing producing it."""
    with pytest.raises(PlanIntegrityError, match="at least one item"):
        _create(_RecordingSession(), items=[])


def test_duplicate_ranks_are_rejected() -> None:
    """Ranks drive the report ordering; duplicates make it nondeterministic.

    The budget is raised well clear of the item total so this test fails for the
    rank reason and not the budget one.
    """
    items = [_item(rank=1), _item(rank=1, tile_key="9q8yz")]
    with pytest.raises(PlanIntegrityError, match="ranks must be unique"):
        _create(_RecordingSession(), budget_usd=D("50000.00"), items=items)


@pytest.mark.parametrize(
    ("low", "point", "high"),
    [("-2.60", "-3.10", "-1.20"), ("-2.60", "-0.10", "-1.20")],
)
def test_plan_interval_must_contain_plan_mean(low: str, point: str, high: str) -> None:
    with pytest.raises(PlanIntegrityError, match="does not contain"):
        _create(
            _RecordingSession(),
            totals=_totals(
                mean_delta_c=D(point),
                mean_delta_c_low=D(low),
                mean_delta_c_high=D(high),
            ),
        )


def test_plan_mean_is_not_derived_from_item_means() -> None:
    """The plan mean is weighted by the optimizer, so it is stored as supplied.

    This test pins the intent: an item mean of -1.90 with a plan mean of -0.80 is
    valid, because the plan mean is area-weighted across the whole AOI including
    untreated tiles.
    """
    session = _RecordingSession()
    plan = _create(
        session,
        items=[_item(predicted_delta_c=D("-1.90"))],
        totals=_totals(
            mean_delta_c=D("-0.80"),
            mean_delta_c_low=D("-1.10"),
            mean_delta_c_high=D("-0.50"),
        ),
    )
    assert getattr(plan, "mean_delta_c") == D("-0.80")


def test_cost_tolerance_is_sub_dollar() -> None:
    """The reconciliation tolerance absorbs rounding, not a real discrepancy."""
    assert Decimal("0") < COST_TOLERANCE_USD < Decimal("1.00")
