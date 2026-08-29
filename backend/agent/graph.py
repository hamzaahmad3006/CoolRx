"""The plan-narration graph (SRS §9.6).

Five nodes, and the shape is the argument:

    load_plan → assemble_evidence → draft_rationales → numeric_guard → compose_report
      (det)          (det)              (llm)             (det)            (llm)

Three of the five are deterministic, and **every number the reader sees is produced
by those three**. The two language-model nodes receive figures as structured input
and return sentences. The guard sits between them, so prose that invented a figure
never reaches the composition step.

That ordering is the whole design. It is why the honesty panel can claim the
language model is not load-bearing, and why `rationale` is nullable in the
database: drop every word the model wrote and the plan is still complete and still
correct.

LangGraph is used as specified. Its value here is not branching — the pipeline is
nearly linear — but that the node set, their order, and the retry edge are declared
as data rather than buried in control flow, so the trace shown on the honesty panel
is generated from the same structure that executed.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Final, TypedDict

import structlog

from schemas.agent import AgentNodeRecord, GuardVerdict, GuardViolation

from .llm import SYSTEM_PROMPT, LlmClient, rationale_prompt, summary_prompt
from .numeric_guard import (
    NUMBER_FREE_RATIONALE,
    AllowedNumerals,
    allowed_from_plan_item,
    check_numerals,
)

log = structlog.get_logger(__name__)

GRAPH_VERSION: Final[str] = "coolrx-graph-1.2"

#: One retry. A model that invents a figure twice will invent it a third time, and
#: each attempt costs tokens and demo seconds; falling back is faster and honest.
MAX_RETRIES: Final[int] = 1


@dataclass(frozen=True, slots=True)
class PlanItemInput:
    """The figures one rationale is allowed to mention."""

    item_id: str
    tile_key: str
    intervention_name: str
    quantity: float
    unit: str
    cost_usd: float
    predicted_delta_c: float
    ci_low_c: float
    ci_high_c: float
    heat_hours_avoided: float
    people_affected: float
    top_driver_label: str
    rank: int
    unit_cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class PlanSummaryInput:
    item_count: int
    block_count: int
    total_cost_usd: float
    mean_delta_c: float
    ci_low_c: float
    ci_high_c: float
    heat_hours_avoided: float
    people_reached: float


class GraphState(TypedDict, total=False):
    """State threaded through the nodes."""

    plan_id: str
    items: list[PlanItemInput]
    summary_input: PlanSummaryInput
    evidence: dict[str, AllowedNumerals]
    drafts: dict[str, str]
    rationales: dict[str, str | None]
    summary: str | None
    violations: list[GuardViolation]
    verdict: GuardVerdict
    nodes: list[AgentNodeRecord]
    tokens_in: int
    tokens_out: int


@dataclass(slots=True)
class AgentRunResult:
    run_id: str
    plan_id: str
    graph_version: str
    model: str
    nodes: list[AgentNodeRecord]
    #: item_id → prose, or None where the guard rejected it. Nullable by design.
    rationales: dict[str, str | None]
    summary: str | None
    verdict: GuardVerdict
    violations: list[GuardViolation] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0


class PlanNarrator:
    """Runs the graph for one plan."""

    def __init__(self, client: LlmClient, *, max_retries: int = MAX_RETRIES) -> None:
        self._client = client
        self._max_retries = max_retries

    def run(
        self,
        *,
        plan_id: str,
        items: list[PlanItemInput],
        summary_input: PlanSummaryInput,
    ) -> AgentRunResult:
        started = time.monotonic()
        graph = self._build_graph()

        initial: GraphState = {
            "plan_id": plan_id,
            "items": items,
            "summary_input": summary_input,
            "evidence": {},
            "drafts": {},
            "rationales": {},
            "summary": None,
            "violations": [],
            "verdict": "pass",
            "nodes": [],
            "tokens_in": 0,
            "tokens_out": 0,
        }

        final: GraphState = graph.invoke(initial)  # type: ignore[assignment]

        result = AgentRunResult(
            # A real UUID, not a prefixed short id. This value becomes the
            # primary key of `agent_runs` and the `{run_id}` in
            # `/api/agent/runs/{run_id}/trace`, both of which are typed UUID --
            # so `run_abc12345` made `uuid.UUID(...)` raise in
            # `plan_pipeline`, where the failure was swallowed as "the trace is
            # not worth a failed plan". The run was never persisted, and the
            # Agent Trace screen answered 404 blaming an unconfigured LLM.
            run_id=str(uuid.uuid4()),
            plan_id=plan_id,
            graph_version=GRAPH_VERSION,
            model=self._client.model_name,
            nodes=final.get("nodes", []),
            rationales=final.get("rationales", {}),
            summary=final.get("summary"),
            verdict=final.get("verdict", "pass"),
            violations=final.get("violations", []),
            tokens_in=final.get("tokens_in", 0),
            tokens_out=final.get("tokens_out", 0),
            duration_ms=int((time.monotonic() - started) * 1000),
        )

        log.info(
            "agent.run_complete",
            plan_id=plan_id,
            verdict=result.verdict,
            violations=len(result.violations),
            rationales=sum(1 for v in result.rationales.values() if v is not None),
            dropped=sum(1 for v in result.rationales.values() if v is None),
        )
        return result

    # ── Graph ────────────────────────────────────────────────────────────────

    def _build_graph(self) -> Any:
        from langgraph.graph import END, START, StateGraph

        builder = StateGraph(GraphState)
        builder.add_node("load_plan", self._load_plan)
        builder.add_node("assemble_evidence", self._assemble_evidence)
        builder.add_node("draft_rationales", self._draft_rationales)
        builder.add_node("numeric_guard", self._numeric_guard)
        builder.add_node("compose_report", self._compose_report)

        builder.add_edge(START, "load_plan")
        builder.add_edge("load_plan", "assemble_evidence")
        builder.add_edge("assemble_evidence", "draft_rationales")
        builder.add_edge("draft_rationales", "numeric_guard")
        builder.add_edge("numeric_guard", "compose_report")
        builder.add_edge("compose_report", END)

        return builder.compile()

    # ── Nodes ────────────────────────────────────────────────────────────────

    def _load_plan(self, state: GraphState) -> GraphState:
        """Deterministic. Validates the inputs the rest of the graph assumes."""
        started = time.monotonic()
        items = state.get("items", [])

        # Rationales are keyed by item id downstream; duplicates would silently
        # overwrite one another and the plan would lose an explanation.
        ids = [item.item_id for item in items]
        if len(set(ids)) != len(ids):
            raise ValueError("plan items must have unique ids")

        return {
            **state,
            "nodes": [
                *state.get("nodes", []),
                _record("load_plan", "deterministic", started),
            ],
        }

    def _assemble_evidence(self, state: GraphState) -> GraphState:
        """Deterministic. Builds each item's allowed numeral set.

        This is where the guard's contract is fixed: the allowed set is derived
        from exactly the figures the prompt will carry, so nothing the model is
        shown is forbidden and nothing forbidden is shown.
        """
        started = time.monotonic()
        evidence = {
            item.item_id: allowed_from_plan_item(
                quantity=item.quantity,
                cost_usd=item.cost_usd,
                predicted_delta_c=item.predicted_delta_c,
                ci_low_c=item.ci_low_c,
                ci_high_c=item.ci_high_c,
                heat_hours_avoided=item.heat_hours_avoided,
                person_heat_hours_avoided=item.heat_hours_avoided
                * item.people_affected,
                people_affected=item.people_affected,
                rank=item.rank,
                unit_cost_usd=item.unit_cost_usd,
            )
            for item in state.get("items", [])
        }
        return {
            **state,
            "evidence": evidence,
            "nodes": [
                *state.get("nodes", []),
                _record("assemble_evidence", "deterministic", started),
            ],
        }

    def _draft_rationales(self, state: GraphState) -> GraphState:
        """Language model. Produces prose only — no figure originates here."""
        started = time.monotonic()
        drafts: dict[str, str] = {}
        tokens_in = state.get("tokens_in", 0)
        tokens_out = state.get("tokens_out", 0)

        for item in state.get("items", []):
            response = self._client.complete(
                system=SYSTEM_PROMPT,
                prompt=rationale_prompt(
                    tile_key=item.tile_key,
                    intervention_name=item.intervention_name,
                    quantity=item.quantity,
                    unit=item.unit,
                    cost_usd=item.cost_usd,
                    predicted_delta_c=item.predicted_delta_c,
                    ci_low_c=item.ci_low_c,
                    ci_high_c=item.ci_high_c,
                    heat_hours_avoided=item.heat_hours_avoided,
                    people_affected=item.people_affected,
                    top_driver_label=item.top_driver_label,
                ),
            )
            drafts[item.item_id] = response.text
            tokens_in += response.tokens_in or 0
            tokens_out += response.tokens_out or 0

        return {
            **state,
            "drafts": drafts,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "nodes": [
                *state.get("nodes", []),
                _record(
                    "draft_rationales",
                    "llm",
                    started,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                ),
            ],
        }

    def _numeric_guard(self, state: GraphState) -> GraphState:
        """Deterministic. The gate.

        Retries once on violation, then drops the prose. Dropping is safe because
        the plan carries no information in the rationale that is not already in the
        table beside it.
        """
        started = time.monotonic()
        evidence = state.get("evidence", {})
        drafts = state.get("drafts", {})

        rationales: dict[str, str | None] = {}
        violations: list[GuardViolation] = []
        retried = False
        dropped = False
        tokens_in = state.get("tokens_in", 0)
        tokens_out = state.get("tokens_out", 0)

        for item in state.get("items", []):
            allowed = evidence.get(item.item_id, AllowedNumerals())
            text = drafts.get(item.item_id, "")
            report = check_numerals(text, allowed, node="draft_rationales")

            if report.passed:
                rationales[item.item_id] = text
                continue

            violations.extend(report.violations)

            accepted: str | None = None
            for _ in range(self._max_retries):
                retried = True
                response = self._client.complete(
                    system=SYSTEM_PROMPT,
                    prompt=(
                        rationale_prompt(
                            tile_key=item.tile_key,
                            intervention_name=item.intervention_name,
                            quantity=item.quantity,
                            unit=item.unit,
                            cost_usd=item.cost_usd,
                            predicted_delta_c=item.predicted_delta_c,
                            ci_low_c=item.ci_low_c,
                            ci_high_c=item.ci_high_c,
                            heat_hours_avoided=item.heat_hours_avoided,
                            people_affected=item.people_affected,
                            top_driver_label=item.top_driver_label,
                        )
                        + "\n\nYour previous answer used a number that was not in "
                        "the data above. Use only the numbers given, or none."
                    ),
                )
                tokens_in += response.tokens_in or 0
                tokens_out += response.tokens_out or 0

                retry_report = check_numerals(
                    response.text, allowed, node="draft_rationales_retry"
                )
                if retry_report.passed:
                    accepted = response.text
                    break
                violations.extend(retry_report.violations)

            if accepted is not None:
                rationales[item.item_id] = accepted
            else:
                # Fail closed. None, not the template: the plan renders the
                # explanation-free state itself, and storing filler prose would
                # make a dropped rationale indistinguishable from a real one.
                rationales[item.item_id] = None
                dropped = True

        verdict: GuardVerdict = (
            "failed" if dropped else ("retried" if retried else "pass")
        )

        return {
            **state,
            "rationales": rationales,
            "violations": violations,
            "verdict": verdict,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "nodes": [
                *state.get("nodes", []),
                _record("numeric_guard", "deterministic", started),
            ],
        }

    def _compose_report(self, state: GraphState) -> GraphState:
        """Language model. The plan's opening paragraph, guarded identically."""
        started = time.monotonic()
        summary_input = state.get("summary_input")
        if summary_input is None:
            return {
                **state,
                "nodes": [
                    *state.get("nodes", []),
                    _record("compose_report", "llm", started, status="skipped"),
                ],
            }

        allowed = AllowedNumerals()
        allowed.add_many(
            [
                summary_input.item_count,
                summary_input.block_count,
                summary_input.total_cost_usd,
                summary_input.mean_delta_c,
                summary_input.ci_low_c,
                summary_input.ci_high_c,
                summary_input.heat_hours_avoided,
                summary_input.people_reached,
            ]
        )

        response = self._client.complete(
            system=SYSTEM_PROMPT,
            prompt=summary_prompt(
                item_count=summary_input.item_count,
                block_count=summary_input.block_count,
                total_cost_usd=summary_input.total_cost_usd,
                mean_delta_c=summary_input.mean_delta_c,
                ci_low_c=summary_input.ci_low_c,
                ci_high_c=summary_input.ci_high_c,
                heat_hours_avoided=summary_input.heat_hours_avoided,
                people_reached=summary_input.people_reached,
            ),
        )

        report = check_numerals(response.text, allowed, node="compose_report")
        violations = [*state.get("violations", []), *report.violations]

        verdict = state.get("verdict", "pass")
        if not report.passed and verdict == "pass":
            verdict = "failed"

        return {
            **state,
            "summary": response.text if report.passed else None,
            "violations": violations,
            "verdict": verdict,
            "tokens_in": state.get("tokens_in", 0) + (response.tokens_in or 0),
            "tokens_out": state.get("tokens_out", 0) + (response.tokens_out or 0),
            "nodes": [
                *state.get("nodes", []),
                _record(
                    "compose_report",
                    "llm",
                    started,
                    tokens_in=response.tokens_in,
                    tokens_out=response.tokens_out,
                ),
            ],
        }


def _record(
    name: str,
    node_type: str,
    started: float,
    *,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    status: str = "completed",
) -> AgentNodeRecord:
    return AgentNodeRecord(
        name=name,
        type=node_type,  # type: ignore[arg-type]
        duration_ms=int((time.monotonic() - started) * 1000),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        status=status,  # type: ignore[arg-type]
    )


__all__ = [
    "GRAPH_VERSION",
    "MAX_RETRIES",
    "NUMBER_FREE_RATIONALE",
    "AgentRunResult",
    "GraphState",
    "PlanItemInput",
    "PlanNarrator",
    "PlanSummaryInput",
]
