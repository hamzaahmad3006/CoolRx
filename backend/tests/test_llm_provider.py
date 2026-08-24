"""Tests for provider selection.

The behaviour that matters is what happens when a key is *absent*. Narration is
optional by design — the numeric guard exists so the language model is not
load-bearing — so a missing provider must leave the plan intact rather than
failing the run.
"""

from __future__ import annotations

import pytest

from agent.llm import AnthropicClient, GroqClient, build_client, pluralise


def _build(**overrides: object) -> object:
    kwargs: dict[str, object] = {
        "provider": "auto",
        "anthropic_api_key": None,
        "groq_api_key": None,
        "anthropic_model": "claude-opus-5",
        "groq_model": "llama-3.3-70b-versatile",
        "max_tokens": 2000,
    }
    kwargs.update(overrides)
    return build_client(**kwargs)  # type: ignore[arg-type]


# ═════════════════════════════════════════════════════════════════════════════
# Selection
# ═════════════════════════════════════════════════════════════════════════════


def test_no_keys_yields_no_client_rather_than_an_error() -> None:
    """A plan without prose is complete; a plan that failed to generate is not."""
    assert _build() is None


def test_auto_prefers_anthropic_when_both_keys_are_present() -> None:
    client = _build(anthropic_api_key="sk-ant-x", groq_api_key="gsk-y")
    assert isinstance(client, AnthropicClient)
    assert client.model_name == "claude-opus-5"


def test_auto_falls_back_to_groq_when_only_groq_is_configured() -> None:
    """The case this exists for: an Anthropic account with no credit."""
    client = _build(groq_api_key="gsk-y")
    assert isinstance(client, GroqClient)
    assert client.model_name == "llama-3.3-70b-versatile"


def test_explicit_groq_ignores_an_anthropic_key() -> None:
    client = _build(provider="groq", anthropic_api_key="sk-ant-x", groq_api_key="gsk-y")
    assert isinstance(client, GroqClient)


def test_explicit_anthropic_does_not_fall_back_to_groq() -> None:
    """An explicit choice is a choice — silently switching providers would make
    the model named on the honesty panel wrong."""
    assert _build(provider="anthropic", groq_api_key="gsk-y") is None


def test_none_disables_narration_even_with_keys_present() -> None:
    assert (
        _build(provider="none", anthropic_api_key="sk-ant-x", groq_api_key="gsk-y")
        is None
    )


@pytest.mark.parametrize("provider", ["AUTO", "Groq", "ANTHROPIC"])
def test_provider_is_case_insensitive(provider: str) -> None:
    """Configuration comes from environment variables, where case is easy to get
    wrong and a silent no-op would look like a missing key."""
    assert (
        _build(provider=provider, anthropic_api_key="k", groq_api_key="k") is not None
    )


# ═════════════════════════════════════════════════════════════════════════════
# The client contract
# ═════════════════════════════════════════════════════════════════════════════


def test_both_clients_report_their_model_for_the_trace() -> None:
    """The honesty panel names the model that produced the text, so a client that
    could not report one would leave the trace unable to say what wrote it."""
    anthropic = AnthropicClient(api_key="k", model="claude-opus-5")
    groq = GroqClient(api_key="k", model="llama-3.3-70b-versatile")
    assert anthropic.model_name == "claude-opus-5"
    assert groq.model_name == "llama-3.3-70b-versatile"


def test_constructing_a_client_makes_no_network_call() -> None:
    """Construction must be free so `build_client` can run during configuration
    without a key being validated, or a plan would fail before it started."""
    GroqClient(api_key="obviously-invalid", model="llama-3.3-70b-versatile")
    AnthropicClient(api_key="obviously-invalid", model="claude-opus-5")


# ═════════════════════════════════════════════════════════════════════════════
# Prompt phrasing
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("unit", "quantity", "expected"),
    [
        ("tree", 12, "trees"),
        ("tree", 1, "tree"),
        ("m2", 400, "m²"),
        ("m2", 1, "m²"),
        ("structure", 3, "structures"),
        ("structure", 1, "structure"),
        ("linear_m", 60, "linear metres"),
        ("station", 2, "stations"),
    ],
)
def test_units_read_naturally_next_to_a_quantity(
    unit: str, quantity: float, expected: str
) -> None:
    """A live Groq run produced "includes 12 tree".

    The model copies the phrasing the prompt gives it, so the fix belongs in the
    prompt rather than in an instruction asking it to correct our grammar. This
    text reaches a document a city department reads.
    """
    assert pluralise(unit, quantity) == expected


def test_an_unknown_unit_still_pluralises_sensibly() -> None:
    """A catalog unit added later must not read as "5 widget"."""
    assert pluralise("widget", 5) == "widgets"


def test_groq_config_defaults_name_a_real_production_model() -> None:
    """Guards against a stale model id, which returns a 404 at request time —
    long after the plan has started and the user is watching progress."""
    from core.config import Settings

    settings = Settings(fixture_mode=True)
    assert settings.groq_model in {
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "openai/gpt-oss-120b",
    }
