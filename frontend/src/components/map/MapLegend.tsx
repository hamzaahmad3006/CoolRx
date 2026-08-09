import { heatLegendStops } from '@/lib/scale';
import { formatNumber } from '@/lib/format';
import { cn } from '@/lib/cn';
import type { EstimateUnit } from '@/types';

interface MapLegendProps {
  /** Analytic name, e.g. "Hours above 35 °C". */
  readonly title: string;
  readonly domain: readonly [number, number];
  /**
   * Unit label. Read from the API response's `stats_data.units` — never assumed,
   * because hour-valued analytics must not be labelled °C (SRS FR-005).
   */
  readonly unit: EstimateUnit;
  readonly unitLabel: string;
  /** Note shown when some tiles have no measurement. */
  readonly hasMissingData?: boolean;
  readonly className?: string;
}

/**
 * Continuous heat-scale legend. Always visible alongside a data layer, and
 * always states its unit — the unit is what makes the colour meaningful.
 */
export function MapLegend({
  title,
  domain,
  unit,
  unitLabel,
  hasMissingData = false,
  className,
}: MapLegendProps) {
  const stops = heatLegendStops(7);
  const [min, max] = domain;
  const gradient = `linear-gradient(to right, ${stops.join(', ')})`;

  return (
    <div
      className={cn(
        'w-56 rounded-sharp border border-line bg-card/95 p-3 backdrop-blur-none',
        className,
      )}
    >
      <p className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
        {title}
      </p>

      <div
        aria-hidden
        className="mt-2 h-2.5 w-full rounded-[2px]"
        style={{ backgroundImage: gradient }}
      />

      <div className="mt-1 flex items-baseline justify-between font-mono text-caption text-ink-secondary" data-numeric>
        <span>{formatNumber(min, unit)}</span>
        <span className="text-ink-muted">{unitLabel}</span>
        <span>{formatNumber(max, unit)}</span>
      </div>

      {hasMissingData ? (
        <p className="mt-2 flex items-center gap-1.5 text-caption text-ink-muted">
          <span
            aria-hidden
            className="size-3 rounded-[2px] border border-line bg-inset"
          />
          No measurement
        </p>
      ) : null}
    </div>
  );
}
