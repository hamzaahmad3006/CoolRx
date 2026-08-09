import type { ExpressionSpecification } from 'maplibre-gl';

import {
  COOLING_SCALE,
  COOLING_SCALE_ZERO_INDEX,
  HEAT_SCALE,
} from '@/constants';

/**
 * Colour-scale interpolation for the data layers.
 *
 * Both ramps are perceptually uniform and colour-blind safe. Interpolation is
 * done in sRGB, which is adequate here because the ramps are already
 * perceptually spaced — the stops do the work, not the interpolation.
 */

interface Rgb {
  readonly r: number;
  readonly g: number;
  readonly b: number;
}

function hexToRgb(hex: string): Rgb {
  const clean = hex.replace('#', '');
  return {
    r: Number.parseInt(clean.slice(0, 2), 16),
    g: Number.parseInt(clean.slice(2, 4), 16),
    b: Number.parseInt(clean.slice(4, 6), 16),
  };
}

function rgbToHex({ r, g, b }: Rgb): string {
  const part = (n: number): string =>
    Math.round(Math.min(255, Math.max(0, n)))
      .toString(16)
      .padStart(2, '0');
  return `#${part(r)}${part(g)}${part(b)}`;
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Sample an ordered ramp at position `t` in [0, 1]. */
function sampleRamp(ramp: readonly string[], t: number): string {
  if (ramp.length === 0) return '#000000';

  const first = ramp[0];
  const last = ramp[ramp.length - 1];
  if (first === undefined || last === undefined) return '#000000';

  const clamped = Math.min(1, Math.max(0, t));
  if (clamped === 0) return first;
  if (clamped === 1) return last;

  const scaled = clamped * (ramp.length - 1);
  const lowIndex = Math.floor(scaled);
  const highIndex = Math.min(ramp.length - 1, lowIndex + 1);
  const low = ramp[lowIndex];
  const high = ramp[highIndex];
  if (low === undefined || high === undefined) return first;

  const localT = scaled - lowIndex;
  const a = hexToRgb(low);
  const b = hexToRgb(high);

  return rgbToHex({
    r: lerp(a.r, b.r, localT),
    g: lerp(a.g, b.g, localT),
    b: lerp(a.b, b.b, localT),
  });
}

/**
 * Map a measured value to a heat colour.
 *
 * A missing value (`null`) returns `null` rather than a colour — the caller must
 * render it as "no data", never as the coolest colour, which would read as a
 * measurement of zero (SRS FR-004).
 */
export function heatColor(
  value: number | null,
  domain: readonly [number, number],
): string | null {
  if (value === null) return null;
  const [min, max] = domain;
  const span = max - min;
  const t = span === 0 ? 0.5 : (value - min) / span;
  return sampleRamp(HEAT_SCALE, t);
}

/**
 * Map a ΔT to a diverging cooling colour, centred on zero.
 *
 * `domain` is the maximum absolute magnitude to display, so that cooling and
 * warming of equal size are equally saturated. Both sides of the before/after
 * view MUST share one domain — a different scale per side would be a visual lie
 * (SRS §28.8).
 */
export function coolingColor(deltaC: number, maxAbs: number): string {
  if (maxAbs === 0) {
    const mid = COOLING_SCALE[COOLING_SCALE_ZERO_INDEX];
    return mid ?? '#e8e6df';
  }
  const clamped = Math.min(maxAbs, Math.max(-maxAbs, deltaC));
  // -maxAbs → 0, 0 → 0.5, +maxAbs → 1
  const t = (clamped + maxAbs) / (2 * maxAbs);
  return sampleRamp(COOLING_SCALE, t);
}

/** Evenly spaced stops for rendering a legend gradient. */
export function heatLegendStops(count = 7): readonly string[] {
  return Array.from({ length: count }, (_, i) =>
    sampleRamp(HEAT_SCALE, count === 1 ? 0 : i / (count - 1)),
  );
}

/**
 * Build a MapLibre `interpolate` paint expression from the heat ramp, so the GPU
 * does the colour mapping instead of JavaScript running per feature. At ~7,000
 * tiles that difference is visible.
 */
export function heatPaintExpression(
  property: string,
  domain: readonly [number, number],
): ExpressionSpecification {
  const [min, max] = domain;
  // Widened to `readonly string[]`: HEAT_SCALE is a fixed-length tuple, so
  // TypeScript rejects a `length === 1` guard against it as impossible.
  const ramp: readonly string[] = HEAT_SCALE;
  const stops = ramp.flatMap<number | string>((color, index) => {
    const t = ramp.length === 1 ? 0 : index / (ramp.length - 1);
    return [min + t * (max - min), color];
  });

  // MapLibre's ExpressionSpecification is a recursive tuple union that cannot
  // express a runtime-built variadic stop list. The array shape is guaranteed
  // correct by construction above: ['interpolate', ['linear'], ['get', prop],
  // stop, colour, ...]. This is the one documented cast in the codebase.
  return [
    'interpolate',
    ['linear'],
    ['get', property],
    ...stops,
  ] as unknown as ExpressionSpecification;
}

/** Round a domain outward to tidy tick values for the legend. */
export function niceDomain(
  min: number,
  max: number,
  step = 1,
): readonly [number, number] {
  return [Math.floor(min / step) * step, Math.ceil(max / step) * step];
}
