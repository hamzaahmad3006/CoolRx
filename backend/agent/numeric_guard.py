"""The numeric guard — deterministic enforcement of principle P1.

P1 says every number in every output originates from the FortyGuard API, the
database, the ML model, or deterministic Python. The language model receives
numbers as structured input and never generates one.

That is a promise, and a promise about a language model is worth nothing without a
mechanism. This module is the mechanism: it extracts every numeral from generated
prose and checks each one against the exact set of values that were supplied to the
model. Anything else is a violation, and a violation means the prose is discarded.

Three design decisions carry most of the weight.

**Strict equality, not tolerance.** If the input says -1.9 °C and the model writes
"about 2 degrees cooler", that is rejected. Rounding is a numeric transformation the
model performed, and a rounded figure in a municipal report is a figure nobody can
trace. Values are compared after parsing, so "1,234.5" and "1234.5" are the same
number, but 2 and 1.9 are not.

**Spelled-out numbers count.** A digit-only regex is trivially bypassed by writing
"twelve trees" instead of "12 trees", and a model asked to vary its phrasing will do
this unprompted. Number words are extracted and checked identically.

**Fail closed.** When violations survive a retry the prose is dropped entirely and
replaced with a number-free template. The plan is still valid — `rationale` is
nullable in the database precisely so the language model is not load-bearing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Final

import structlog

from schemas.agent import GuardViolation, NumericGuardReport

log = structlog.get_logger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# Extraction
# ═════════════════════════════════════════════════════════════════════════════

#: Digit runs, with optional sign, thousands separators and a decimal part.
#: A trailing ordinal suffix is consumed so "12th" is caught as the numeral 12 —
#: an invented rank is exactly as misleading as an invented measurement.
_DIGIT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""
    # Not glued to the end of an alphanumeric token, and not preceded by a dot.
    # The dot matters for identifiers like "PM2.5": the 2 is already excluded by
    # the letter before it, but without excluding "." the trailing 5 would be read
    # as a standalone numeral. Real decimals are unaffected because a value like
    # 1.9 is matched as one token starting at its first digit.
    (?<![A-Za-z0-9.])
    (?P<sign>[-+−])?       # ASCII hyphen, plus, or Unicode minus
    (?P<number>
        \d{1,3}(?:,\d{3})+(?:\.\d+)?   # 1,234 or 1,234.56
      | \d+(?:\.\d+)?                  # 1234 or 1234.56
    )
    (?:st|nd|rd|th)?            # ordinal suffix
    (?![A-Za-z0-9.,]*\d)        # not the middle of a longer alphanumeric run
    """,
    re.VERBOSE,
)

#: Number words. Cardinals up to twenty plus the tens, which covers the range a
#: model actually spells out in prose; larger values are written as digits.
_NUMBER_WORDS: Final[dict[str, Decimal]] = {
    "zero": Decimal(0), "one": Decimal(1), "two": Decimal(2), "three": Decimal(3),
    "four": Decimal(4), "five": Decimal(5), "six": Decimal(6), "seven": Decimal(7),
    "eight": Decimal(8), "nine": Decimal(9), "ten": Decimal(10),
    "eleven": Decimal(11), "twelve": Decimal(12), "thirteen": Decimal(13),
    "fourteen": Decimal(14), "fifteen": Decimal(15), "sixteen": Decimal(16),
    "seventeen": Decimal(17), "eighteen": Decimal(18), "nineteen": Decimal(19),
    "twenty": Decimal(20), "thirty": Decimal(30), "forty": Decimal(40),
    "fifty": Decimal(50), "sixty": Decimal(60), "seventy": Decimal(70),
    "eighty": Decimal(80), "ninety": Decimal(90), "hundred": Decimal(100),
    "thousand": Decimal(1000), "million": Decimal(1_000_000),
    # Ordinals, which a model reaches for when ranking items.
    "first": Decimal(1), "second": Decimal(2), "third": Decimal(3),
    "fourth": Decimal(4), "fifth": Decimal(5), "sixth": Decimal(6),
    "seventh": Decimal(7), "eighth": Decimal(8), "ninth": Decimal(9),
    "tenth": Decimal(10),
    # Fractions and multipliers, which assert a quantitative relationship just as
    # firmly as a digit does.
    "half": Decimal("0.5"), "quarter": Decimal("0.25"),
    "double": Decimal(2), "twice": Decimal(2), "triple": Decimal(3),
}

_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

#: Words that read as numeric words but assert no specific quantity, so they are
#: not treated as numerals. "One of the hottest blocks" makes no claim about a
#: count; blocking it would force stilted prose for no safety gain.
#: This list is deliberately short — every entry is a hole in the guard.
_NON_QUANTITATIVE: Final[frozenset[str]] = frozenset({"one of", "one to", "on one"})


@dataclass(frozen=True, slots=True)
class NumeralToken:
    """One numeral found in generated text."""

    raw: str
    value: Decimal
    start: int
    end: int
    #: True when written as a word rather than digits.
    is_word: bool

    def context(self, text: str, window: int = 40) -> str:
        """Surrounding text, for the trace.

        The token alone does not reveal whether the model invented a figure or
        merely reformatted an allowed one, and that distinction is the whole
        diagnostic value of the agent trace.
        """
        left = max(0, self.start - window)
        right = min(len(text), self.end + window)
        prefix = "…" if left > 0 else ""
        suffix = "…" if right < len(text) else ""
        return f"{prefix}{text[left:right].strip()}{suffix}"


def _to_decimal(raw: str, sign: str | None) -> Decimal | None:
    try:
        value = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None
    if sign in {"-", "−"}:
        return -value
    return value


def extract_numerals(text: str) -> list[NumeralToken]:
    """Every numeral in the text, digits and number words alike.

    Ordered by position so the trace reads in the same order as the prose.
    """
    tokens: list[NumeralToken] = []

    for match in _DIGIT_PATTERN.finditer(text):
        value = _to_decimal(match.group("number"), match.group("sign"))
        if value is None:
            continue
        tokens.append(
            NumeralToken(
                raw=match.group(0),
                value=value,
                start=match.start(),
                end=match.end(),
                is_word=False,
            )
        )

    lowered = text.lower()
    for match in _WORD_PATTERN.finditer(text):
        word = match.group(1).lower()
        # Skip the handful of phrasings that use a number word non-quantitatively.
        window = lowered[max(0, match.start() - 3) : match.end() + 4]
        if any(phrase in window for phrase in _NON_QUANTITATIVE):
            continue
        tokens.append(
            NumeralToken(
                raw=match.group(0),
                value=_NUMBER_WORDS[word],
                start=match.start(),
                end=match.end(),
                is_word=True,
            )
        )

    tokens.sort(key=lambda token: token.start)
    return tokens


# ═════════════════════════════════════════════════════════════════════════════
# The allowed set
# ═════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class AllowedNumerals:
    """The exact values the model was given.

    Built from the structured input the prompt carried, so it is impossible for a
    value to be allowed that the model was not handed. Nothing is added by
    inference — an allowed set that grew by "reasonable rounding" would readmit the
    exact failure the guard exists to catch.
    """

    values: set[Decimal] = field(default_factory=set)
    #: Literal strings permitted regardless of their numerals — model versions and
    #: identifiers like "lgbm-2026.08.1", where the digits are a name, not a claim.
    literals: set[str] = field(default_factory=set)

    def add(self, value: float | int | Decimal | None) -> None:
        if value is None:
            return
        as_decimal = Decimal(str(value))
        self.values.add(as_decimal)
        # A value's integral form is admitted only when it is genuinely integral,
        # so 12.0 permits "12" but 1.9 does not permit "2".
        if as_decimal == as_decimal.to_integral_value():
            self.values.add(as_decimal.to_integral_value())

    def add_many(self, values: Iterable[float | int | Decimal | None]) -> None:
        for value in values:
            self.add(value)

    def add_literal(self, literal: str) -> None:
        self.literals.add(literal)

    def permits(self, value: Decimal) -> bool:
        return value in self.values

    def as_sorted_strings(self) -> list[str]:
        return [str(value) for value in sorted(self.values)]


def allowed_from_plan_item(
    *,
    quantity: float,
    cost_usd: float,
    predicted_delta_c: float,
    ci_low_c: float,
    ci_high_c: float,
    heat_hours_avoided: float,
    person_heat_hours_avoided: float,
    people_affected: float,
    rank: int,
    unit_cost_usd: float | None = None,
    model_version: str | None = None,
) -> AllowedNumerals:
    """The allowed set for a per-item rationale.

    Mirrors exactly the fields the rationale prompt is given. Adding a field here
    without adding it to the prompt would widen the guard for no reason; adding it
    to the prompt without adding it here would make every generation fail.
    """
    allowed = AllowedNumerals()
    allowed.add_many(
        [
            quantity,
            cost_usd,
            predicted_delta_c,
            ci_low_c,
            ci_high_c,
            heat_hours_avoided,
            person_heat_hours_avoided,
            people_affected,
            rank,
            unit_cost_usd,
        ]
    )
    if model_version:
        allowed.add_literal(model_version)
    return allowed


# ═════════════════════════════════════════════════════════════════════════════
# The check
# ═════════════════════════════════════════════════════════════════════════════


def _mask_literals(text: str, literals: Iterable[str]) -> str:
    """Blank out permitted literals so their digits are not scanned.

    A model version like "lgbm-2026.08.1" contains numerals that are part of a name.
    Masking is done by length-preserving replacement so token offsets stay valid for
    the context windows in the trace.
    """
    masked = text
    for literal in literals:
        if literal and literal in masked:
            masked = masked.replace(literal, "_" * len(literal))
    return masked


def check_numerals(
    text: str, allowed: AllowedNumerals, *, node: str = "unknown"
) -> NumericGuardReport:
    """Verify that every numeral in `text` came from the structured input."""
    masked = _mask_literals(text, allowed.literals)
    tokens = extract_numerals(masked)

    violations: list[GuardViolation] = []
    for token in tokens:
        if allowed.permits(token.value):
            continue
        violations.append(
            GuardViolation(
                node=node,
                token=token.raw,
                context=token.context(text),
                reason=(
                    f"The value {token.value} was not supplied to the model. "
                    + (
                        "It is written as a word, which a digit-only check would "
                        "have missed."
                        if token.is_word
                        else "Only values passed as structured input may appear."
                    )
                ),
            )
        )

    passed = not violations
    if not passed:
        log.warning(
            "numeric_guard.violations",
            node=node,
            count=len(violations),
            tokens=[v.token for v in violations],
        )

    return NumericGuardReport(
        passed=passed,
        allowed_tokens=allowed.as_sorted_strings(),
        violations=violations,
        fell_back=False,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Fail-closed fallback
# ═════════════════════════════════════════════════════════════════════════════

#: Used when generated prose cannot be trusted. Contains no numerals at all, so it
#: is safe by construction rather than by inspection.
NUMBER_FREE_RATIONALE: Final[str] = (
    "This intervention was selected by the optimizer for its cost-effectiveness on "
    "this block. The figures in the table beside this note come from the model and "
    "the intervention catalog; see the methods page for how each is derived."
)


def fallback_report(
    previous: NumericGuardReport, *, node: str = "unknown"
) -> NumericGuardReport:
    """Mark a report as having fallen back to the number-free template.

    The violations are kept, not cleared. The agent trace is a product feature that
    answers "did a language model make up any of these numbers?", and the honest
    answer here is "yes, and it was caught" — which is the system working.
    """
    log.warning(
        "numeric_guard.fell_back",
        node=node,
        violations=len(previous.violations),
    )
    return NumericGuardReport(
        passed=False,
        allowed_tokens=previous.allowed_tokens,
        violations=previous.violations,
        fell_back=True,
    )


def guard_text(
    text: str,
    allowed: AllowedNumerals,
    *,
    node: str = "unknown",
    regenerate: Sequence[str] = (),
) -> tuple[str | None, NumericGuardReport]:
    """Check text, optionally retry with regenerated candidates, else fail closed.

    Returns `(accepted_text, report)`. `accepted_text` is None only when the caller
    should store no rationale at all; the number-free template is returned as text
    when a retry is exhausted, so the UI still has something to render.

    Candidates are supplied rather than generated here on purpose: this module stays
    free of LLM calls so it can be tested exhaustively and cheaply, and so the guard
    itself cannot fail because a network call did.
    """
    report = check_numerals(text, allowed, node=node)
    if report.passed:
        return text, report

    for candidate in regenerate:
        retry = check_numerals(candidate, allowed, node=node)
        if retry.passed:
            log.info("numeric_guard.retry_succeeded", node=node)
            return candidate, retry

    return NUMBER_FREE_RATIONALE, fallback_report(report, node=node)
