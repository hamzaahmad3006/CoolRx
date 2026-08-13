"""Tests for the numeric guard.

Almost every test here is adversarial. A guard that only passes the happy path is
worse than no guard, because it produces a compliance claim the system does not
actually meet — and P1 is the claim this project is built on.

The bypasses tested include: spelled-out numbers, rounding, unit conversion,
percentage rescaling, thousands separators, ordinals, and derived arithmetic the
model performed on values it was legitimately given.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from agent.numeric_guard import (
    NUMBER_FREE_RATIONALE,
    AllowedNumerals,
    allowed_from_plan_item,
    check_numerals,
    extract_numerals,
    guard_text,
)


def _allowed(*values: float) -> AllowedNumerals:
    allowed = AllowedNumerals()
    allowed.add_many(values)
    return allowed


# ═════════════════════════════════════════════════════════════════════════════
# Extraction
# ═════════════════════════════════════════════════════════════════════════════


def test_extracts_plain_integers_and_decimals() -> None:
    tokens = extract_numerals("Plant 12 trees for a 1.9 degree reduction.")
    assert [t.value for t in tokens] == [Decimal("12"), Decimal("1.9")]


def test_extracts_thousands_separated_values() -> None:
    tokens = extract_numerals("The cost is 1,234,567 dollars.")
    assert tokens[0].value == Decimal("1234567")


def test_extracts_negative_values() -> None:
    """Cooling is negative throughout the system; the sign must survive."""
    tokens = extract_numerals("A change of -2.3 °C is expected.")
    assert tokens[0].value == Decimal("-2.3")


def test_extracts_unicode_minus() -> None:
    """A model producing typographically correct prose uses U+2212, not a hyphen."""
    tokens = extract_numerals("A change of −2.3 °C.")
    assert tokens[0].value == Decimal("-2.3")


def test_extracts_ordinal_digits() -> None:
    """An invented rank misleads as much as an invented measurement."""
    tokens = extract_numerals("This is the 4th priority block.")
    assert tokens[0].value == Decimal("4")


def test_ignores_digits_inside_identifiers() -> None:
    """`PM2.5` and `CO2` are names, not quantitative claims."""
    tokens = extract_numerals("Reduces CO2 and PM2.5 exposure.")
    assert tokens == []


def test_extracts_spelled_out_numbers() -> None:
    """The bypass a digit-only regex misses entirely."""
    tokens = extract_numerals("Plant twelve trees.")
    assert tokens[0].value == Decimal("12")
    assert tokens[0].is_word is True


def test_extracts_spelled_out_ordinals_and_fractions() -> None:
    for text, expected in [
        ("the third block", Decimal("3")),
        ("half the population", Decimal("0.5")),
        ("twice the benefit", Decimal("2")),
    ]:
        assert extract_numerals(text)[0].value == expected


def test_number_words_are_case_insensitive() -> None:
    assert extract_numerals("Twelve trees")[0].value == Decimal("12")


def test_tokens_are_ordered_by_position() -> None:
    tokens = extract_numerals("First 5 then twelve then 3.")
    assert [t.start for t in tokens] == sorted(t.start for t in tokens)


def test_non_quantitative_phrasing_is_not_flagged() -> None:
    """"One of the hottest blocks" asserts no count.

    Blocking it would force stilted prose for no safety gain.
    """
    assert extract_numerals("This is one of the hottest blocks.") == []


# ═════════════════════════════════════════════════════════════════════════════
# The core guarantee
# ═════════════════════════════════════════════════════════════════════════════


def test_supplied_values_pass() -> None:
    allowed = _allowed(12, 5400.0, -1.9)
    report = check_numerals(
        "Planting 12 trees at a cost of 5400 dollars yields -1.9 °C.", allowed
    )
    assert report.passed
    assert report.violations == []


def test_an_invented_number_is_caught() -> None:
    report = check_numerals("This will help roughly 850 residents.", _allowed(12))
    assert not report.passed
    assert report.violations[0].token == "850"


def test_rounding_is_caught() -> None:
    """The subtle one.

    Given -1.9, a model writing "about 2 degrees" has performed a numeric
    transformation. The rounded figure is untraceable to any stored value, which is
    exactly what P2 forbids.
    """
    report = check_numerals("Expect about 2 degrees of cooling.", _allowed(-1.9))
    assert not report.passed


def test_unit_conversion_is_caught() -> None:
    """-1.9 °C is 3.42 °F. The model must not convert."""
    report = check_numerals("That is 3.42 °F cooler.", _allowed(-1.9))
    assert not report.passed


def test_percentage_rescaling_is_caught() -> None:
    """Given 0.4, writing "40%" is a transformation, not a restatement."""
    report = check_numerals("It reaches 40% of residents.", _allowed(0.4))
    assert not report.passed


def test_derived_arithmetic_is_caught() -> None:
    """Given 12 trees at 450 each, the model must not compute 5400 itself.

    The total is a real figure — but it must come from the optimizer, so that the
    number displayed and the number stored are the same object.
    """
    report = check_numerals("Twelve trees at 450 each totals 5400.", _allowed(12, 450))
    tokens = {v.token for v in report.violations}
    assert not report.passed
    assert "5400" in tokens


def test_spelled_out_invention_is_caught() -> None:
    """The bypass that motivates word extraction."""
    report = check_numerals("Plant twenty trees.", _allowed(12))
    assert not report.passed
    assert report.violations[0].token.lower() == "twenty"
    assert "word" in report.violations[0].reason


def test_thousands_separator_formatting_is_accepted() -> None:
    """Formatting is not transformation: 1,234.5 and 1234.5 are one value."""
    report = check_numerals("Avoids 1,234.5 person-heat-hours.", _allowed(1234.5))
    assert report.passed


def test_integral_value_permits_its_bare_form() -> None:
    """12.0 supplied permits "12" written, because they are the same number."""
    assert check_numerals("Plant 12 trees.", _allowed(12.0)).passed


def test_non_integral_value_does_not_permit_its_rounding() -> None:
    """The asymmetry that matters: 1.9 must not admit 2."""
    assert not check_numerals("About 2 degrees.", _allowed(1.9)).passed


def test_every_violation_is_reported_not_just_the_first() -> None:
    report = check_numerals("Helps 850 people over 30 years at 99 sites.", _allowed(12))
    assert {v.token for v in report.violations} == {"850", "30", "99"}


def test_violation_carries_its_context() -> None:
    """The token alone cannot show whether a figure was invented or reformatted."""
    report = check_numerals(
        "Shading the transit stop reaches 850 daily riders in this block.",
        _allowed(12),
    )
    assert "riders" in report.violations[0].context


def test_report_lists_what_was_allowed() -> None:
    """The trace must show the guard's inputs, not just its verdict."""
    report = check_numerals("Plant 12 trees.", _allowed(12, -1.9))
    assert set(report.allowed_tokens) >= {"12", "-1.9"}


def test_prose_with_no_numbers_passes() -> None:
    report = check_numerals(
        "This block was selected for its dense paving and lack of shade.",
        AllowedNumerals(),
    )
    assert report.passed


def test_empty_allowed_set_rejects_every_numeral() -> None:
    assert not check_numerals("Plant 12 trees.", AllowedNumerals()).passed


# ═════════════════════════════════════════════════════════════════════════════
# Literals
# ═════════════════════════════════════════════════════════════════════════════


def test_model_version_digits_are_not_treated_as_claims() -> None:
    """"lgbm-2026.08.1" is a name; its digits assert nothing."""
    allowed = AllowedNumerals()
    allowed.add_literal("lgbm-2026.08.1")
    report = check_numerals("Produced by model lgbm-2026.08.1.", allowed)
    assert report.passed


def test_masking_a_literal_does_not_hide_a_real_violation() -> None:
    """Masking must be length-preserving so nearby tokens are still found."""
    allowed = AllowedNumerals()
    allowed.add_literal("lgbm-2026.08.1")
    report = check_numerals(
        "Model lgbm-2026.08.1 predicts 850 people affected.", allowed
    )
    assert not report.passed
    assert report.violations[0].token == "850"
    assert "people" in report.violations[0].context


# ═════════════════════════════════════════════════════════════════════════════
# Retry and fail-closed
# ═════════════════════════════════════════════════════════════════════════════


def test_clean_text_is_returned_unchanged() -> None:
    text = "Planting 12 trees cools this block."
    accepted, report = guard_text(text, _allowed(12))
    assert accepted == text
    assert report.passed and not report.fell_back


def test_a_clean_retry_is_accepted() -> None:
    accepted, report = guard_text(
        "Helps about 850 people.",
        _allowed(12),
        regenerate=["Planting 12 trees cools this block."],
    )
    assert accepted == "Planting 12 trees cools this block."
    assert report.passed
    assert not report.fell_back


def test_exhausted_retries_fall_back_to_the_number_free_template() -> None:
    accepted, report = guard_text(
        "Helps 850 people.",
        _allowed(12),
        regenerate=["Still helps 850 people.", "Roughly 900 people."],
    )
    assert accepted == NUMBER_FREE_RATIONALE
    assert report.fell_back
    assert not report.passed


def test_the_fallback_template_contains_no_numerals() -> None:
    """Safe by construction rather than by inspection."""
    assert extract_numerals(NUMBER_FREE_RATIONALE) == []


def test_the_fallback_passes_its_own_guard_with_nothing_allowed() -> None:
    """The strongest form of the previous test."""
    assert check_numerals(NUMBER_FREE_RATIONALE, AllowedNumerals()).passed


def test_fallback_keeps_the_violations_for_the_trace() -> None:
    """The trace answers "did the model invent a number?" — honestly, "yes, caught"."""
    _, report = guard_text("Helps 850 people.", _allowed(12), regenerate=[])
    assert report.fell_back
    assert len(report.violations) == 1
    assert report.violations[0].token == "850"


# ═════════════════════════════════════════════════════════════════════════════
# Allowed-set construction
# ═════════════════════════════════════════════════════════════════════════════


def test_plan_item_allowed_set_covers_every_prompt_field() -> None:
    allowed = allowed_from_plan_item(
        quantity=12,
        cost_usd=5400.0,
        predicted_delta_c=-1.9,
        ci_low_c=-2.6,
        ci_high_c=-1.2,
        heat_hours_avoided=310.0,
        person_heat_hours_avoided=18400.0,
        people_affected=640.0,
        rank=1,
        unit_cost_usd=450.0,
        model_version="lgbm-2026.08.1",
    )
    text = (
        "Ranked 1: plant 12 trees at 450 each, 5400 total. Cools this block by "
        "-1.9 °C (-2.6 to -1.2), avoiding 310 hours above threshold and 18400 "
        "person-heat-hours for 640 residents. Model lgbm-2026.08.1."
    )
    assert check_numerals(text, allowed).passed


def test_none_values_are_skipped_not_added_as_zero() -> None:
    """A missing unit cost must not silently permit the numeral 0."""
    allowed = AllowedNumerals()
    allowed.add(None)
    assert not check_numerals("It costs 0 dollars.", allowed).passed


@pytest.mark.parametrize(
    "sneaky",
    [
        "Roughly 850 residents benefit.",
        "Around twenty trees are needed.",
        "This is the 3rd hottest block.",
        "Costs about $5,401 in total.",
        "Reduces temperature by 2 degrees.",
        "Half of the residents are over 65.",
        "Expect a 15% improvement.",
    ],
)
def test_a_battery_of_invented_figures_is_caught(sneaky: str) -> None:
    """Phrasings a model reaches for when asked to sound natural."""
    allowed = _allowed(12, 5400.0, -1.9)
    assert not check_numerals(sneaky, allowed).passed, f"missed: {sneaky!r}"
