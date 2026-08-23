"""Plan and plan-item persistence.

A plan is written as one transaction with its items. A plan row whose totals do
not match its items would be a plan that reports a budget it did not spend, so
the totals are recomputed from the items here rather than trusted from the
caller, and the database CHECK constraints are the backstop.

Every predicted value is stored with its interval. The interval columns are NOT
NULL and CHECK-ordered, which makes a bare point estimate unstorable — the
persistence-layer counterpart of the frontend `Estimate` type.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .tables import Plan, PlanItem

log = structlog.get_logger(__name__)

VALID_OBJECTIVES: Final[frozenset[str]] = frozenset(
    {"max_delta_c", "max_person_heat_hours", "equity_weighted"}
)

#: Tolerance for the totals reconciliation, in dollars. Item costs are stored at
#: cent precision, so a sum of many items can differ from a separately rounded
#: total by a few cents without indicating a real discrepancy.
COST_TOLERANCE_USD: Final[Decimal] = Decimal("0.05")


class PlanIntegrityError(ValueError):
    """Raised when a plan and its items disagree, before anything is written."""


@dataclass(frozen=True, slots=True)
class PlanItemInput:
    """One optimizer selection.

    The interval fields are required. A caller cannot construct an item that
    carries a prediction without one.
    """

    tile_key: str
    intervention_code: str
    quantity: Decimal
    cost_usd: Decimal
    predicted_delta_c: Decimal
    ci_low_c: Decimal
    ci_high_c: Decimal
    heat_hours_avoided: Decimal
    person_heat_hours_avoided: Decimal
    people_affected: Decimal
    rank: int
    marginal_benefit_per_usd: Decimal
    rationale: str | None = None

    def __post_init__(self) -> None:
        if not (self.ci_low_c <= self.predicted_delta_c <= self.ci_high_c):
            raise PlanIntegrityError(
                f"{self.intervention_code}@{self.tile_key}: interval "
                f"[{self.ci_low_c}, {self.ci_high_c}] does not contain "
                f"{self.predicted_delta_c}"
            )
        if self.quantity <= 0:
            raise PlanIntegrityError(
                f"{self.intervention_code}@{self.tile_key}: quantity must be positive"
            )
        if self.cost_usd < 0:
            raise PlanIntegrityError(
                f"{self.intervention_code}@{self.tile_key}: cost must not be negative"
            )


@dataclass(frozen=True, slots=True)
class PlanTotalsInput:
    """Plan-level aggregates.

    `mean_delta_c` is an area- or population-weighted mean computed by the
    optimizer, not the arithmetic mean of the item deltas, so it is supplied
    rather than derived. The cost total *is* derived and cross-checked.
    """

    mean_delta_c: Decimal
    mean_delta_c_low: Decimal
    mean_delta_c_high: Decimal
    heat_hours_avoided: Decimal
    person_heat_hours_avoided: Decimal
    people_reached: Decimal


class PlanRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def session(self) -> Session:
        """The unit of work this repository is part of.

        Exposed so a caller already holding this repository can enlist a sibling
        one in the same transaction, rather than opening a second session that
        could commit independently of the plan it describes.
        """
        return self._session

    def create(
        self,
        *,
        project_id: uuid.UUID,
        budget_usd: Decimal,
        objective: str,
        equity_lambda: Decimal,
        threshold_c: Decimal,
        model_version: str,
        items: Sequence[PlanItemInput],
        totals: PlanTotalsInput,
    ) -> Plan:
        """Persist a plan and its items in one transaction.

        Validates before writing so a rejected plan produces an actionable
        message instead of an IntegrityError naming a constraint.
        """
        if objective not in VALID_OBJECTIVES:
            raise PlanIntegrityError(
                f"unknown objective {objective!r}; expected one of "
                f"{sorted(VALID_OBJECTIVES)}"
            )
        if budget_usd <= 0:
            raise PlanIntegrityError("budget must be positive")
        if not items:
            raise PlanIntegrityError(
                "a plan must contain at least one item; an empty plan would "
                "report a benefit with nothing to attribute it to"
            )
        if not (
            totals.mean_delta_c_low <= totals.mean_delta_c <= totals.mean_delta_c_high
        ):
            raise PlanIntegrityError(
                f"plan interval [{totals.mean_delta_c_low}, "
                f"{totals.mean_delta_c_high}] does not contain {totals.mean_delta_c}"
            )

        # Recomputed, not trusted: the stored total must be the sum of what was
        # actually selected.
        total_cost = sum((item.cost_usd for item in items), Decimal("0"))
        if total_cost > budget_usd:
            raise PlanIntegrityError(
                f"items total ${total_cost} exceeds budget ${budget_usd}; "
                "the optimizer must not return an over-budget selection"
            )

        ranks = [item.rank for item in items]
        if len(set(ranks)) != len(ranks):
            raise PlanIntegrityError("plan item ranks must be unique")

        plan = Plan(
            project_id=project_id,
            budget_usd=budget_usd,
            objective=objective,
            equity_lambda=equity_lambda,
            threshold_c=threshold_c,
            model_version=model_version,
            total_cost_usd=total_cost,
            mean_delta_c=totals.mean_delta_c,
            mean_delta_c_low=totals.mean_delta_c_low,
            mean_delta_c_high=totals.mean_delta_c_high,
            heat_hours_avoided=totals.heat_hours_avoided,
            person_heat_hours_avoided=totals.person_heat_hours_avoided,
            people_reached=totals.people_reached,
        )
        self._session.add(plan)
        self._session.flush()

        self._session.add_all(
            PlanItem(
                plan_id=plan.id,
                tile_key=item.tile_key,
                intervention_code=item.intervention_code,
                quantity=item.quantity,
                cost_usd=item.cost_usd,
                predicted_delta_c=item.predicted_delta_c,
                ci_low_c=item.ci_low_c,
                ci_high_c=item.ci_high_c,
                heat_hours_avoided=item.heat_hours_avoided,
                person_heat_hours_avoided=item.person_heat_hours_avoided,
                people_affected=item.people_affected,
                rank=item.rank,
                marginal_benefit_per_usd=item.marginal_benefit_per_usd,
                rationale=item.rationale,
            )
            for item in items
        )
        self._session.flush()

        log.info(
            "plan.created",
            plan_id=str(plan.id),
            project_id=str(project_id),
            items=len(items),
            total_cost_usd=str(total_cost),
            budget_usd=str(budget_usd),
            model_version=model_version,
        )
        return plan

    def get(self, plan_id: uuid.UUID) -> Plan | None:
        return self._session.get(Plan, plan_id)

    def get_with_items(self, plan_id: uuid.UUID) -> Plan | None:
        """Load a plan and its items in one round-trip.

        `selectinload` rather than lazy loading: the report renderer touches
        every item, and lazy loading would issue one query per item.
        """
        stmt = (
            select(Plan)
            .options(selectinload(Plan.items))
            .where(Plan.id == plan_id)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def items(self, plan_id: uuid.UUID) -> list[PlanItem]:
        stmt = (
            select(PlanItem)
            .where(PlanItem.plan_id == plan_id)
            .order_by(PlanItem.rank)
        )
        return list(self._session.execute(stmt).scalars())

    def list_for_project(self, project_id: uuid.UUID, limit: int = 20) -> list[Plan]:
        stmt = (
            select(Plan)
            .where(Plan.project_id == project_id)
            .order_by(Plan.created_at.desc())
            .limit(limit)
        )
        return list(self._session.execute(stmt).scalars())

    def set_rationale(self, item_id: uuid.UUID, rationale: str | None) -> bool:
        """Attach LLM prose to an item after the fact.

        Separate from `create` because the plan is complete without it: the agent
        runs after the plan is persisted, and a failed agent run must leave a
        valid plan behind rather than roll one back.
        """
        item = self._session.get(PlanItem, item_id)
        if item is None:
            return False
        item.rationale = rationale
        return True

    def verify_totals(self, plan_id: uuid.UUID) -> tuple[bool, str | None]:
        """Re-check a persisted plan against its items.

        Used by the report step: the numbers about to be printed are re-derived
        from the items and compared, so a plan that drifted cannot be exported.
        """
        plan = self.get_with_items(plan_id)
        if plan is None:
            return False, "plan not found"

        item_total = sum(
            (Decimal(str(item.cost_usd)) for item in plan.items), Decimal("0")
        )
        stored_total = Decimal(str(plan.total_cost_usd))
        if abs(item_total - stored_total) > COST_TOLERANCE_USD:
            return False, (
                f"stored total ${stored_total} does not match item sum ${item_total}"
            )
        if stored_total > Decimal(str(plan.budget_usd)):
            return False, (
                f"stored total ${stored_total} exceeds budget ${plan.budget_usd}"
            )
        return True, None
