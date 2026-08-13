'use client';

import { ATTRIBUTION_COLORS, TEXT } from '@/constants';
import { formatNumber } from '@/lib/format';
import type { AttributionDriver } from '@/types';

interface ShapWaterfallProps {
  readonly drivers: readonly AttributionDriver[];
  /** Cap the rows shown; the rest are summarised. */
  readonly maxRows?: number;
}

/**
 * Per-tile SHAP contributions as a diverging bar chart.
 *
 * Built from divs rather than Recharts on purpose. A diverging bar anchored at a
 * shared zero, with the label on the outside and the value in a fixed column, is
 * a layout problem rather than a charting one — and this way every bar is a real
 * DOM node, so the whole thing is readable by a screen reader and selectable as
 * text. SRS §28.7 requires the sign to be legible without colour, which is why
 * each row carries an explicit "warmer"/"cooler" word.
 *
 * Bars are scaled against the largest absolute contribution, so the widest bar
 * always fills the track and small contributions stay visible.
 */
export function ShapWaterfall({ drivers, maxRows = 6 }: ShapWaterfallProps) {
  if (drivers.length === 0) {
    return (
      <p className="text-sm text-ink-secondary">
        No attribution is available for this block.
      </p>
    );
  }

  const shown = drivers.slice(0, maxRows);
  const hidden = drivers.slice(maxRows);
  const peak = Math.max(...drivers.map((d) => Math.abs(d.contributionC)), 0.01);

  const hiddenTotal = hidden.reduce((sum, d) => sum + d.contributionC, 0);

  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-col gap-1.5">
        {shown.map((driver) => (
          <DriverRow key={driver.feature} driver={driver} peak={peak} />
        ))}
      </ul>

      {hidden.length > 0 && (
        <p className="text-xs text-ink-secondary">
          {hidden.length} smaller {hidden.length === 1 ? 'driver' : 'drivers'} account
          for {formatNumber(Math.abs(hiddenTotal), 'celsius')} °C combined.
        </p>
      )}
    </div>
  );
}

function DriverRow({
  driver,
  peak,
}: {
  readonly driver: AttributionDriver;
  readonly peak: number;
}) {
  const warming = driver.contributionC > 0;
  const width = `${Math.min(100, (Math.abs(driver.contributionC) / peak) * 100)}%`;
  const color = warming ? ATTRIBUTION_COLORS.warming : ATTRIBUTION_COLORS.cooling;

  return (
    <li className="grid grid-cols-[9rem_1fr_4.5rem] items-center gap-2">
      <span className="truncate text-xs text-ink-secondary" title={driver.label}>
        {driver.label}
      </span>

      {/* Two half-tracks meeting at a shared centre, so bars diverge from one
          axis and opposing drivers are visually comparable. */}
      <span className="grid h-4 grid-cols-2" aria-hidden="true">
        <span className="relative border-r border-line">
          {!warming && (
            <span
              className="absolute right-0 top-0 h-full rounded-l-[2px]"
              style={{ width, backgroundColor: color }}
            />
          )}
        </span>
        <span className="relative">
          {warming && (
            <span
              className="absolute left-0 top-0 h-full rounded-r-[2px]"
              style={{ width, backgroundColor: color }}
            />
          )}
        </span>
      </span>

      <span
        className="text-right text-xs tabular-nums"
        style={{ color: TEXT.primary }}
        data-numeric
      >
        {/* The sign word carries the meaning when colour is unavailable. */}
        <span className="sr-only">{warming ? 'warmer by ' : 'cooler by '}</span>
        {warming ? '+' : '-'}
        {formatNumber(Math.abs(driver.contributionC), 'celsius')} °C
      </span>
    </li>
  );
}
