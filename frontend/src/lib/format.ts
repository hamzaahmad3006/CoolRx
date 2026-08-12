import type { EstimateUnit } from '@/types';

/**
 * Number and unit formatting — the single source of truth.
 *
 * ⚠️ This module is half of a cross-stack contract. The backend's
 * `numeric_guard` (SRS §9.6.2) validates that every numeral appearing in
 * LLM-authored prose also exists in the source payload. It does that by
 * comparing *formatted* renderings, so the backend's formatter and this module
 * must agree on every value class. If you change a format here, change it there.
 *
 * Formatting decisions:
 *  - Plain ASCII hyphen-minus for negatives, not U+2212. It survives copy-paste,
 *    the PDF pipeline and the guard's token matching without an encoding class
 *    of bugs. Typographic purity is not worth that trade.
 *  - Precision is capped at what the method actually supports. False precision
 *    (a ΔT to three decimals) misrepresents a planning-grade estimate.
 */

/** Precision per unit — never exceed what the method supports. */
const PRECISION: Readonly<Record<EstimateUnit, number>> = {
  celsius: 1,
  hour: 0,
  person_hour: 0,
  usd: 0,
  people: 0,
  count: 0,
};

const UNIT_SUFFIX: Readonly<Record<EstimateUnit, string>> = {
  celsius: ' °C',
  hour: ' h',
  person_hour: '',
  usd: '',
  people: '',
  count: '',
};

/** Format a bare number at the precision its unit supports, with thousands separators. */
export function formatNumber(value: number, unit: EstimateUnit): string {
  const digits = PRECISION[unit];
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Format a value with its unit, e.g. `-2.3 °C`, `5,820 h`, `$400,000`. */
export function formatValue(value: number, unit: EstimateUnit): string {
  if (unit === 'usd') return formatCurrency(value);
  return `${formatNumber(value, unit)}${UNIT_SUFFIX[unit]}`;
}

/** Whole-dollar currency. Cooling budgets are never quoted in cents. */
export function formatCurrency(value: number): string {
  return value.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

/**
 * Compact currency for slider bubbles and tight columns: `$400K`, `$1.2M`.
 * Full precision is always available in the adjacent numeric input.
 */
export function formatCurrencyCompact(value: number): string {
  if (Math.abs(value) >= 1_000_000) {
    return `$${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
  }
  if (Math.abs(value) >= 1_000) {
    return `$${Math.round(value / 1_000)}K`;
  }
  return formatCurrency(value);
}

/** Percentage from a 0–1 fraction, e.g. `61%`. */
export function formatPercent(fraction: number, digits = 0): string {
  return `${(fraction * 100).toFixed(digits)}%`;
}

/** Percentage from an already-scaled 0–100 value. */
export function formatPercentScaled(value: number, digits = 0): string {
  return `${value.toFixed(digits)}%`;
}

/**
 * A prediction interval, e.g. `(-3.0 to -1.6)`.
 * Never rendered without an accompanying point value.
 */
export function formatInterval(
  low: number,
  high: number,
  unit: EstimateUnit,
): string {
  return `(${formatNumber(low, unit)} to ${formatNumber(high, unit)})`;
}

/**
 * Hour-of-day as local clock time, e.g. `16:00`.
 * FortyGuard returns `time_of_measure` in UTC; convert before calling this.
 */
export function formatHourOfDay(hour: number): string {
  const clamped = Math.max(0, Math.min(23, Math.round(hour)));
  return `${String(clamped).padStart(2, '0')}:00`;
}

/** Duration in hours, e.g. `9 h`, `1 h`. */
export function formatHours(hours: number): string {
  return `${formatNumber(hours, 'hour')} h`;
}

/** Area in square miles against the API cap, e.g. `1.54 mi²`. */
export function formatAreaSqMi(areaSqMi: number): string {
  return `${areaSqMi.toFixed(2)} mi²`;
}

/**
 * A value that may be missing.
 *
 * FortyGuard returns `null` for unavailable readings, and older records use a
 * `-999` sentinel. Both mean missing and must NEVER render as zero (SRS FR-008).
 */
export function formatMaybe(
  value: number | null,
  unit: EstimateUnit,
  fallback = 'unavailable',
): string {
  if (value === null) return fallback;
  return formatValue(value, unit);
}

/**
 * An em dash, used for a missing value in a numeric table cell.
 *
 * Deliberately not `0`, not `-` and not an empty cell: a zero would read as a
 * measurement, a hyphen is ambiguous with a minus sign in a column of negative
 * temperatures, and an empty cell looks like a rendering fault.
 */
export const MISSING_MARK = '—';

/**
 * Bare number that may be missing — for table cells whose column header already
 * carries the unit, so appending it again would repeat it in every row.
 */
export function formatNumberMaybe(
  value: number | null,
  unit: EstimateUnit,
  fallback: string = MISSING_MARK,
): string {
  if (value === null) return fallback;
  return formatNumber(value, unit);
}

/** Hour of day that may be missing. */
export function formatHourOfDayMaybe(
  hour: number | null,
  fallback: string = MISSING_MARK,
): string {
  if (hour === null) return fallback;
  return formatHourOfDay(hour);
}

/** Truncate a long identifier for display, keeping it recognisable. */
export function truncateId(id: string, visible = 8): string {
  return id.length <= visible ? id : `${id.slice(0, visible)}…`;
}

/**
 * Normalise a formatted numeric token for comparison.
 *
 * Mirrors the backend guard's normalisation so that `18,400`, `18400` and
 * `$18,400` all reduce to the same key. Exported for tests that assert the
 * cross-stack contract holds.
 */
export function normalizeNumericToken(token: string): string {
  return token.replace(/[,$\s°ChmiÂ²]/g, '').replace(/^\+/, '');
}
