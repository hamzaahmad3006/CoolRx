import { GLOSSARY } from '@/constants';
import { formatInterval, formatValue } from '@/lib/format';
import { cn } from '@/lib/cn';
import type { Estimate as EstimateValue } from '@/types';
import { Tag } from './Tag';
import { Tooltip } from './Tooltip';

/**
 * ═══════════════════════════════════════════════════════════════════════════
 * THE SANCTIONED RENDERER FOR A PREDICTED VALUE.
 *
 * SRS §20.3 forbids displaying a model prediction without its uncertainty
 * interval, and this component is how that rule is enforced structurally rather
 * than by convention:
 *
 *   - It accepts an `Estimate`, whose `ciLow` and `ciHigh` are REQUIRED fields.
 *     A bare point estimate is unrepresentable in the type system.
 *   - It always renders the interval alongside the point value.
 *   - It always carries an "est." marker.
 *
 * A predicted ΔT, heat-hours-avoided or person-heat-hours figure rendered any
 * other way is a review failure. Measured values (a FortyGuard reading, a cost,
 * a population count) are NOT estimates and should use `formatValue` directly.
 * ═══════════════════════════════════════════════════════════════════════════
 */

export type EstimateSize = 'inline' | 'block' | 'hero';

interface EstimateProps {
  readonly estimate: EstimateValue;
  /**
   * `inline` — one line, for table cells.
   * `block`  — point value over the interval, for panels.
   * `hero`   — large point value with a range bar, for stat tiles.
   */
  readonly size?: EstimateSize;
  /** Show the "est." marker. Default true — only suppress where an adjacent
   *  label already states the value is predicted. */
  readonly showMarker?: boolean;
  readonly showRangeBar?: boolean;
  readonly className?: string;
}

export function Estimate({
  estimate,
  size = 'inline',
  showMarker = true,
  showRangeBar = size === 'hero',
  className,
}: EstimateProps) {
  const { value, ciLow, ciHigh, unit } = estimate;

  const point = formatValue(value, unit);
  const interval = formatInterval(ciLow, ciHigh, unit);

  const pointClass =
    size === 'hero'
      ? 'text-title font-semibold text-accent-strong'
      : size === 'block'
        ? 'text-heading font-semibold text-ink'
        : 'text-body font-medium text-ink';

  return (
    <span
      className={cn(
        size === 'inline'
          ? 'inline-flex items-baseline gap-1.5'
          : 'flex flex-col gap-1',
        className,
      )}
      data-numeric
    >
      <span className={cn('flex items-baseline gap-2', size === 'inline' && 'contents')}>
        <span className={pointClass}>{point}</span>

        <Tooltip content={GLOSSARY.predictionInterval}>
          <span className="cursor-help text-caption text-ink-secondary underline decoration-dotted decoration-from-font underline-offset-2">
            {interval}
          </span>
        </Tooltip>

        {showMarker ? (
          <Tooltip content={GLOSSARY.predictedDelta}>
            <Tag variant="neutral" className="cursor-help">
              est.
            </Tag>
          </Tooltip>
        ) : null}
      </span>

      {showRangeBar ? <RangeBar low={ciLow} value={value} high={ciHigh} /> : null}
    </span>
  );
}

interface RangeBarProps {
  readonly low: number;
  readonly value: number;
  readonly high: number;
}

/**
 * Slim visual of the prediction interval. The track spans [low, high]; the
 * marker sits at the point estimate's position within it.
 */
function RangeBar({ low, value, high }: RangeBarProps) {
  const span = high - low;
  const fraction = span === 0 ? 0.5 : (value - low) / span;
  const clamped = Math.min(1, Math.max(0, fraction));

  return (
    <span
      aria-hidden
      className="relative mt-1 block h-1.5 w-full max-w-48 rounded-[2px] bg-accent-subtle"
    >
      <span
        className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 bg-accent"
        style={{ left: `${clamped * 100}%` }}
      />
    </span>
  );
}
