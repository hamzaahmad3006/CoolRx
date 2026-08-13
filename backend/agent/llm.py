"""The language-model boundary.

An interface, not a client. Everything above it — the graph, the guard, the node
trace — is exercised in tests with a scripted stand-in, so the pipeline's behaviour
under a model that fabricates figures can be tested exhaustively and for free.
That matters more here than usual: the interesting cases are the ones where the
model misbehaves, and those are hard to provoke on demand from a real API.

The prompt-building functions live here too, next to the guard's allowed-set
construction, because the two must agree. A figure added to a prompt without being
added to the allowed set makes every generation fail the guard; one added to the
allowed set without reaching the prompt silently widens what the model may say.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Final

import structlog

log = structlog.get_logger(__name__)

#: Instruction shared by every prompt. States the numeric rule to the model as
#: well as enforcing it afterwards — the guard is the guarantee, but a model told
#: the rule up front violates it far less often, which saves a retry round-trip.
SYSTEM_PROMPT: Final[str] = (
    "You write short, plain explanations for a city heat-mitigation plan, for an "
    "audience of municipal planners.\n\n"
    "Absolute rule: you may only use numbers that appear verbatim in the data "
    "given to you. Do not round them, convert their units, compute totals or "
    "percentages from them, or write any figure as a word. If you want to express "
    "a quantity you were not given, describe it in words instead — say 'most of "
    "the block' rather than inventing a share.\n\n"
    "Do not claim any intervention will cause a specific outcome. These are "
    "planning estimates, not guarantees. Write two sentences at most."
)


@dataclass(frozen=True, slots=True)
class LlmResponse:
    text: str
    tokens_in: int | None = None
    tokens_out: int | None = None


class LlmClient(ABC):
    """What the graph needs from a language model. Nothing more."""

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def complete(self, *, system: str, prompt: str) -> LlmResponse: ...


class AnthropicClient(LlmClient):
    """Production client.

    The SDK is imported lazily so the graph can be imported, and tested, without
    the dependency or an API key present.
    """

    def __init__(self, *, api_key: str, model: str, max_tokens: int = 1024) -> None:
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, *, system: str, prompt: str) -> LlmResponse:
        import anthropic

        client = anthropic.Anthropic(api_key=self._api_key)
        message = client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )

        text = "".join(
            block.text for block in message.content if block.type == "text"
        )
        return LlmResponse(
            text=text.strip(),
            tokens_in=message.usage.input_tokens,
            tokens_out=message.usage.output_tokens,
        )


@dataclass(slots=True)
class ScriptedClient(LlmClient):
    """Test double returning canned responses in order.

    Exists so the guard can be exercised against a model that *does* fabricate
    figures — the case that matters and the one a real API will not produce
    reliably.
    """

    responses: list[str]
    model: str = "scripted-test"
    calls: list[str] = field(default_factory=list)

    @property
    def model_name(self) -> str:
        return self.model

    def complete(self, *, system: str, prompt: str) -> LlmResponse:
        self.calls.append(prompt)
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        if not self.responses:
            return LlmResponse(text="", tokens_in=0, tokens_out=0)
        return LlmResponse(
            text=self.responses[index], tokens_in=100, tokens_out=40
        )


# ═════════════════════════════════════════════════════════════════════════════
# Prompts
# ═════════════════════════════════════════════════════════════════════════════


def rationale_prompt(
    *,
    tile_key: str,
    intervention_name: str,
    quantity: float,
    unit: str,
    cost_usd: float,
    predicted_delta_c: float,
    ci_low_c: float,
    ci_high_c: float,
    heat_hours_avoided: float,
    people_affected: float,
    top_driver_label: str,
) -> str:
    """Prompt for one plan item's rationale.

    Every figure interpolated here must also be in the allowed set built by
    `allowed_from_plan_item`. The two lists are deliberately the same length and
    the same values; a test asserts a generation reproducing all of them passes.
    """
    return (
        f"Block {tile_key} was selected for the cooling plan.\n\n"
        f"Data:\n"
        f"- Intervention: {intervention_name}\n"
        f"- Quantity: {quantity} {unit}\n"
        f"- Cost: {cost_usd} USD\n"
        f"- Predicted temperature change: {predicted_delta_c} °C "
        f"(range {ci_low_c} to {ci_high_c})\n"
        f"- Dangerous hours avoided: {heat_hours_avoided}\n"
        f"- Residents affected: {people_affected}\n"
        f"- Main reason this block is hot: {top_driver_label}\n\n"
        "Explain in at most two sentences why this intervention was chosen for "
        "this block. Refer to the main reason it is hot."
    )


def summary_prompt(
    *,
    item_count: int,
    block_count: int,
    total_cost_usd: float,
    mean_delta_c: float,
    ci_low_c: float,
    ci_high_c: float,
    heat_hours_avoided: float,
    people_reached: float,
) -> str:
    """Prompt for the plan's opening paragraph."""
    return (
        f"A cooling plan has been generated.\n\n"
        f"Data:\n"
        f"- Interventions: {item_count}\n"
        f"- Blocks treated: {block_count}\n"
        f"- Total cost: {total_cost_usd} USD\n"
        f"- Mean temperature change across the district: {mean_delta_c} °C "
        f"(range {ci_low_c} to {ci_high_c})\n"
        f"- Dangerous hours avoided: {heat_hours_avoided}\n"
        f"- People reached: {people_reached}\n\n"
        "Write a two-sentence opening for the plan document summarising what it "
        "does. Do not promise an outcome."
    )
