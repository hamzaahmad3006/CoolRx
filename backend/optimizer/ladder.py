"""The exceedance ladder.

This is the idea the project is built on, so it is worth stating precisely.

FortyGuard's `exceedance` analytic answers one question: *how many hours was this
tile above threshold T?* Ask it eleven times, at T, T+1, … T+10, and you have a
per-tile curve of hours-above-threshold as a function of threshold. That curve is
measured, not modelled.

Given a predicted cooling of ΔT, the hours a tile spends above the danger threshold
after the intervention is read off the same curve at T + |ΔT|:

    hours_avoided = ladder(T) − ladder(T + |ΔT|)

So a temperature change becomes an exposure change **using the API's own analytic
rather than a model of our own**. The output is in hours of dangerous heat avoided,
which is a unit a public-health officer already reasons in — unlike degrees.

The assumption, stated wherever a figure derived from it appears
(`LADDER_ASSUMPTION` in `schemas/common.py`): cooling is applied as a **uniform
diurnal shift**. Real cooling varies by hour — shade trees do most of their work at
solar noon, cool roofs at peak insolation — so the whole curve is shifted rather
than reshaped. That makes these order-of-magnitude planning figures, not forecasts.

Two further limits are enforced rather than assumed away:

  * **ΔT beyond the ladder's top rung cannot be evaluated.** Extrapolating past
    T+10 would invent hours the API never measured, so it is refused.
  * **Hours are non-increasing in threshold.** A ladder that rises somewhere is
    physically impossible and indicates a bad response; it is repaired and logged
    rather than silently propagated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import structlog

log = structlog.get_logger(__name__)

#: Rungs above the base threshold. Eleven calls total, counting T itself.
LADDER_STEPS: Final[int] = 10

#: Cooling beyond this cannot be converted to hours — the ladder does not reach.
MAX_EVALUABLE_DELTA_C: Final[float] = float(LADDER_STEPS)


class LadderError(ValueError):
    """The ladder cannot answer for this input."""


@dataclass(frozen=True, slots=True)
class TileLadder:
    """One tile's hours-above-threshold curve.

    `hours[i]` is hours above `base_threshold_c + i`. Index 0 is the danger
    threshold itself.
    """

    tile_key: str
    base_threshold_c: float
    hours: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.hours) < 2:
            raise LadderError(
                f"{self.tile_key}: a ladder needs at least two rungs, got "
                f"{len(self.hours)}"
            )
        if any(value < 0 for value in self.hours):
            raise LadderError(f"{self.tile_key}: hours cannot be negative")
        if any(value > 24 for value in self.hours):
            raise LadderError(
                f"{self.tile_key}: hours above 24 in a single-day window"
            )

    @property
    def top_of_ladder_c(self) -> float:
        return self.base_threshold_c + (len(self.hours) - 1)

    def hours_at(self, threshold_c: float) -> float:
        """Hours above an arbitrary threshold, interpolated between rungs.

        Linear interpolation, because the ladder is sampled at whole degrees and a
        predicted ΔT rarely lands on one. The curve is monotone and smooth over a
        1 °C span, so linear is the honest choice — a spline would imply precision
        between rungs that was never measured.
        """
        if threshold_c < self.base_threshold_c:
            raise LadderError(
                f"{self.tile_key}: {threshold_c} °C is below the ladder's base "
                f"{self.base_threshold_c} °C; hours there were never measured"
            )
        if threshold_c > self.top_of_ladder_c:
            raise LadderError(
                f"{self.tile_key}: {threshold_c} °C is above the ladder's top rung "
                f"{self.top_of_ladder_c} °C; extrapolating would invent hours the "
                "API never measured"
            )

        offset = threshold_c - self.base_threshold_c
        lower = int(offset)
        if lower >= len(self.hours) - 1:
            return self.hours[-1]

        weight = offset - lower
        return self.hours[lower] * (1 - weight) + self.hours[lower + 1] * weight

    def hours_avoided(self, delta_c: float) -> float:
        """Hours above the danger threshold removed by cooling of `delta_c`.

        `delta_c` is the cooling magnitude and is expected negative, matching the
        sign convention used everywhere else (cooling is negative). A positive
        value describes warming and yields zero avoided hours rather than a
        negative one — warming does not "avoid" a negative number of hours, and
        letting that through would let a bad intervention improve a plan's total.
        """
        magnitude = -delta_c
        if magnitude <= 0:
            return 0.0
        if magnitude > MAX_EVALUABLE_DELTA_C:
            raise LadderError(
                f"{self.tile_key}: cooling of {magnitude} °C exceeds the ladder's "
                f"reach of {MAX_EVALUABLE_DELTA_C} °C"
            )

        before = self.hours[0]
        after = self.hours_at(self.base_threshold_c + magnitude)
        # Clamped at zero: floating error on a flat curve can produce -1e-15,
        # which would render as "-0 hours avoided".
        return max(0.0, before - after)

    @property
    def is_already_safe(self) -> bool:
        """True when the tile never exceeds the danger threshold.

        Such a tile cannot benefit in hours-avoided terms no matter how much it is
        cooled, which is a meaningful planning fact rather than a zero to hide.
        """
        return self.hours[0] <= 0.0


def build_ladder(
    *,
    tile_key: str,
    base_threshold_c: float,
    hours_by_step: dict[int, float | None],
    steps: int = LADDER_STEPS,
) -> TileLadder | None:
    """Assemble a ladder from the analytic runs, or None if it cannot be trusted.

    `hours_by_step` maps rung index (0 = base threshold) to measured hours. A None
    means that rung's analytic returned nothing for this tile.

    Returns None rather than filling gaps. An interpolated rung would be a
    fabricated measurement standing where a real one is missing, and every figure
    downstream — hours avoided, person-heat-hours, cost per hour — would inherit it
    with no way to tell.
    """
    missing = [index for index in range(steps + 1) if hours_by_step.get(index) is None]
    if missing:
        log.debug(
            "ladder.incomplete",
            tile_key=tile_key,
            missing_steps=missing,
            detail="tile excluded from hours-avoided accounting",
        )
        return None

    raw = [float(hours_by_step[index]) for index in range(steps + 1)]  # type: ignore[arg-type]
    repaired = _enforce_monotonic(tile_key, raw)

    return TileLadder(
        tile_key=tile_key,
        base_threshold_c=base_threshold_c,
        hours=tuple(repaired),
    )


def _enforce_monotonic(tile_key: str, hours: list[float]) -> list[float]:
    """Hours above a threshold cannot rise as the threshold rises.

    A rung higher than the one below it is physically impossible. It is clamped to
    its predecessor and logged, because the alternative — propagating it — produces
    a *negative* hours-avoided figure that would show an intervention making things
    worse for reasons that are actually an upstream data artefact.
    """
    out = list(hours)
    repaired = 0
    for index in range(1, len(out)):
        if out[index] > out[index - 1]:
            repaired += 1
            out[index] = out[index - 1]

    if repaired:
        log.warning(
            "ladder.non_monotonic_repaired",
            tile_key=tile_key,
            rungs_clamped=repaired,
            detail=(
                "Hours-above-threshold rose with threshold, which is impossible. "
                "Clamped to the preceding rung."
            ),
        )
    return out


def person_heat_hours(hours: float, population: float | None) -> float | None:
    """Population × hours. None when population is unknown.

    None rather than 0: a tile with unknown population is not a tile with nobody in
    it, and treating it as empty would systematically deprioritise exactly the areas
    where census coverage is worst.
    """
    if population is None:
        return None
    return hours * population


def equity_weighted(
    person_hours: float | None, svi_score: float | None, equity_lambda: float
) -> float | None:
    """`PHH × (1 + λ·SVI)`.

    λ is a policy choice supplied by the caller, never a constant. A missing SVI
    contributes no uplift rather than blocking the calculation — the tile is still
    ranked on its raw exposure, just without an equity adjustment it has no data for.
    """
    if person_hours is None:
        return None
    return person_hours * (1.0 + equity_lambda * (svi_score or 0.0))
