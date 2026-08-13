"""Tests for the narration graph.

Driven by a scripted client so the interesting cases — a model that fabricates a
figure, then does it again on retry — can be provoked on demand. A real API will
not reliably misbehave, and those are exactly the paths that must work.

The claim under test is the one the honesty panel makes: **the language model is
not load-bearing.** Drop every word it wrote and the plan is still complete.
"""

from __future__ import annotations

import pytest

from agent.graph import (
    GRAPH_VERSION,
    PlanItemInput,
    PlanNarrator,
    PlanSummaryInput,
)
from agent.llm import ScriptedClient

pytest.importorskip("langgraph")


def _item(item_id: str = "item-1") -> PlanItemInput:
    return PlanItemInput(
        item_id=item_id,
        tile_key="9tbq2p3xj",
        intervention_name="Medium street tree",
        quantity=12,
        unit="tree",
        cost_usd=5400,
        predicted_delta_c=-1.9,
        ci_low_c=-2.6,
        ci_high_c=-1.2,
        heat_hours_avoided=310,
        people_affected=640,
        top_driver_label="Paved and built surface",
        rank=1,
        unit_cost_usd=450,
    )


def _summary() -> PlanSummaryInput:
    return PlanSummaryInput(
        item_count=1,
        block_count=1,
        total_cost_usd=5400,
        mean_delta_c=-1.9,
        ci_low_c=-2.6,
        ci_high_c=-1.2,
        heat_hours_avoided=310,
        people_reached=640,
    )


#: Uses only supplied figures.
CLEAN = (
    "This block is dominated by paved surface, so planting 12 trees targets the "
    "main driver of its heat. The work costs 5400 and is predicted to change "
    "temperature by -1.9 °C."
)

#: Prose with no numerals at all — always safe.
NUMBER_FREE = (
    "This block is dominated by paved surface, so planting street trees targets "
    "the main driver of its heat."
)

#: Invents a figure that was never supplied.
FABRICATED = (
    "Planting here will help roughly 850 nearby residents during the afternoon "
    "peak."
)


def _run(responses: list[str]) -> tuple[object, ScriptedClient]:
    client = ScriptedClient(responses=responses)
    narrator = PlanNarrator(client)
    result = narrator.run(
        plan_id="plan-1", items=[_item()], summary_input=_summary()
    )
    return result, client


# ═════════════════════════════════════════════════════════════════════════════
# Shape
# ═════════════════════════════════════════════════════════════════════════════


def test_all_five_nodes_run_in_order() -> None:
    result, _ = _run([CLEAN, NUMBER_FREE])
    names = [node.name for node in result.nodes]  # type: ignore[attr-defined]
    assert names == [
        "load_plan",
        "assemble_evidence",
        "draft_rationales",
        "numeric_guard",
        "compose_report",
    ]


def test_three_of_five_nodes_are_deterministic() -> None:
    """The structural claim: every number comes from the deterministic nodes."""
    result, _ = _run([CLEAN, NUMBER_FREE])
    kinds = [node.type for node in result.nodes]  # type: ignore[attr-defined]
    assert kinds.count("deterministic") == 3
    assert kinds.count("llm") == 2


def test_the_guard_runs_before_the_composition_node() -> None:
    """Ordering is the design: fabricated prose must not reach composition."""
    result, _ = _run([CLEAN, NUMBER_FREE])
    names = [node.name for node in result.nodes]  # type: ignore[attr-defined]
    assert names.index("numeric_guard") < names.index("compose_report")


def test_run_reports_its_graph_version() -> None:
    result, _ = _run([CLEAN, NUMBER_FREE])
    assert result.graph_version == GRAPH_VERSION  # type: ignore[attr-defined]


def test_duplicate_item_ids_are_rejected() -> None:
    """Rationales are keyed by id; duplicates would silently overwrite."""
    narrator = PlanNarrator(ScriptedClient(responses=[CLEAN]))
    with pytest.raises(ValueError, match="unique ids"):
        narrator.run(
            plan_id="p",
            items=[_item("dup"), _item("dup")],
            summary_input=_summary(),
        )


# ═════════════════════════════════════════════════════════════════════════════
# Clean path
# ═════════════════════════════════════════════════════════════════════════════


def test_a_clean_generation_passes_and_is_kept() -> None:
    result, _ = _run([CLEAN, NUMBER_FREE])
    assert result.verdict == "pass"  # type: ignore[attr-defined]
    assert result.violations == []  # type: ignore[attr-defined]
    assert result.rationales["item-1"] == CLEAN  # type: ignore[attr-defined]


def test_tokens_are_accumulated_across_llm_nodes() -> None:
    result, _ = _run([CLEAN, NUMBER_FREE])
    assert result.tokens_in > 0  # type: ignore[attr-defined]
    assert result.tokens_out > 0  # type: ignore[attr-defined]


# ═════════════════════════════════════════════════════════════════════════════
# Fabrication
# ═════════════════════════════════════════════════════════════════════════════


def test_a_fabricated_figure_triggers_a_retry() -> None:
    """First response invents 850; the retry is clean."""
    result, client = _run([FABRICATED, CLEAN, NUMBER_FREE])
    assert result.verdict == "retried"  # type: ignore[attr-defined]
    assert result.rationales["item-1"] == CLEAN  # type: ignore[attr-defined]
    assert any(v.token == "850" for v in result.violations)  # type: ignore[attr-defined]
    # Drafting, retry, then the summary.
    assert len(client.calls) == 3


def test_the_retry_prompt_tells_the_model_what_went_wrong() -> None:
    _, client = _run([FABRICATED, CLEAN, NUMBER_FREE])
    assert "not in the data above" in client.calls[1]


def test_persistent_fabrication_drops_the_prose() -> None:
    """Fail closed. The model invented a figure twice, so nothing is kept."""
    result, _ = _run([FABRICATED, FABRICATED, NUMBER_FREE])
    assert result.verdict == "failed"  # type: ignore[attr-defined]
    assert result.rationales["item-1"] is None  # type: ignore[attr-defined]


def test_violations_are_retained_after_a_drop() -> None:
    """The honesty panel's job is to show the mechanism firing, not hide it."""
    result, _ = _run([FABRICATED, FABRICATED, NUMBER_FREE])
    assert len(result.violations) >= 2  # type: ignore[attr-defined]
    assert all(v.token == "850" for v in result.violations)  # type: ignore[attr-defined]


def test_the_plan_survives_every_rationale_being_dropped() -> None:
    """The load-bearing claim, tested directly.

    Every rationale is None and the run still completes with a verdict, a node
    trace and its violations — which is what makes `rationale` nullable in the
    database rather than a column the report depends on.
    """
    result, _ = _run([FABRICATED, FABRICATED, NUMBER_FREE])
    assert all(v is None for v in result.rationales.values())  # type: ignore[attr-defined]
    assert result.verdict == "failed"  # type: ignore[attr-defined]
    assert len(result.nodes) == 5  # type: ignore[attr-defined]


def test_a_fabricated_summary_is_discarded_not_shown() -> None:
    """The composition node is guarded on the same terms as the rationales."""
    result, _ = _run([CLEAN, FABRICATED])
    assert result.summary is None  # type: ignore[attr-defined]
    assert result.verdict == "failed"  # type: ignore[attr-defined]


def test_a_clean_summary_is_kept() -> None:
    result, _ = _run([CLEAN, NUMBER_FREE])
    assert result.summary == NUMBER_FREE  # type: ignore[attr-defined]


# ═════════════════════════════════════════════════════════════════════════════
# Prompt and allowed-set agreement
# ═════════════════════════════════════════════════════════════════════════════


def test_a_response_echoing_every_supplied_figure_passes() -> None:
    """The prompt and the allowed set must agree.

    A figure in the prompt but not the allowed set makes every generation fail; one
    in the allowed set but not the prompt silently widens what the model may say.
    """
    echoed = (
        "Rank 1: 12 trees at 450 each, 5400 total, changing temperature by "
        "-1.9 °C between -2.6 and -1.2, avoiding 310 hours for 640 residents."
    )
    result, _ = _run([echoed, NUMBER_FREE])
    assert result.verdict == "pass"  # type: ignore[attr-defined]
    assert result.rationales["item-1"] == echoed  # type: ignore[attr-defined]


def test_number_free_prose_always_passes() -> None:
    result, _ = _run([NUMBER_FREE, NUMBER_FREE])
    assert result.verdict == "pass"  # type: ignore[attr-defined]


def test_the_system_prompt_states_the_numeric_rule() -> None:
    """Telling the model the rule reduces retries; the guard still enforces it."""
    from agent.llm import SYSTEM_PROMPT

    lowered = SYSTEM_PROMPT.lower()
    assert "only use numbers that appear" in lowered
    assert "do not round" in lowered
    assert "as a word" in lowered


def test_the_system_prompt_forbids_causal_claims() -> None:
    from agent.llm import SYSTEM_PROMPT

    assert "cause" in SYSTEM_PROMPT.lower()
    assert "not guarantees" in SYSTEM_PROMPT.lower()
