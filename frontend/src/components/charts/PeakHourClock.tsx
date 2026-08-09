import { ACCENT, HEAT_SCALE, SURFACE, TEXT } from '@/constants';
import { formatHourOfDay } from '@/lib/format';

interface PeakHourClockProps {
  /** Local hour of day, 0–23, when the district peaks. */
  readonly peakHourLocal: number;
  /**
   * Optional per-hour distribution of how many blocks peak in that hour.
   * Index 0–23. Rendered as radial bars when supplied.
   */
  readonly hourHistogram?: readonly number[];
  readonly size?: number;
}

/**
 * 24-hour radial plot of when heat peaks.
 *
 * Unconventional, but genuinely the clearest encoding for hour-of-day: a linear
 * axis breaks the cyclical relationship and puts 23:00 and 00:00 at opposite
 * ends. Peak timing changes where shade must go, so it earns a dedicated view
 * (SRS §28.6).
 *
 * Hand-drawn SVG rather than a chart library — a 24-segment radial is less code
 * than configuring one, and stays crisp at any size.
 */
export function PeakHourClock({
  peakHourLocal,
  hourHistogram,
  size = 168,
}: PeakHourClockProps) {
  const center = size / 2;
  const outerRadius = center - 18;
  const innerRadius = outerRadius * 0.52;

  const maxCount =
    hourHistogram === undefined
      ? 0
      : hourHistogram.reduce((max, value) => Math.max(max, value), 0);

  const hours = Array.from({ length: 24 }, (_, hour) => hour);

  /** Hour 0 at the top, clockwise — matches a clock face. */
  const angleFor = (hour: number): number => (hour / 24) * Math.PI * 2 - Math.PI / 2;

  return (
    <figure className="flex flex-col items-center gap-2">
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={`Peak heat occurs at ${formatHourOfDay(peakHourLocal)} local time`}
      >
        {/* Track */}
        <circle
          cx={center}
          cy={center}
          r={(outerRadius + innerRadius) / 2}
          fill="none"
          stroke={SURFACE.inset}
          strokeWidth={outerRadius - innerRadius}
        />

        {/* Radial bars for the per-hour distribution */}
        {hourHistogram !== undefined && maxCount > 0
          ? hours.map((hour) => {
              const count = hourHistogram[hour] ?? 0;
              if (count === 0) return null;
              const fraction = count / maxCount;
              const angle = angleFor(hour);
              const barOuter = innerRadius + (outerRadius - innerRadius) * fraction;
              const colorIndex = Math.min(
                HEAT_SCALE.length - 1,
                Math.floor(fraction * (HEAT_SCALE.length - 1)),
              );
              return (
                <line
                  key={hour}
                  x1={center + Math.cos(angle) * innerRadius}
                  y1={center + Math.sin(angle) * innerRadius}
                  x2={center + Math.cos(angle) * barOuter}
                  y2={center + Math.sin(angle) * barOuter}
                  stroke={HEAT_SCALE[colorIndex] ?? HEAT_SCALE[0]}
                  strokeWidth={(Math.PI * 2 * innerRadius) / 24 - 2}
                  strokeLinecap="butt"
                />
              );
            })
          : null}

        {/* Peak marker */}
        <line
          x1={center + Math.cos(angleFor(peakHourLocal)) * (innerRadius - 4)}
          y1={center + Math.sin(angleFor(peakHourLocal)) * (innerRadius - 4)}
          x2={center + Math.cos(angleFor(peakHourLocal)) * (outerRadius + 6)}
          y2={center + Math.sin(angleFor(peakHourLocal)) * (outerRadius + 6)}
          stroke={ACCENT.base}
          strokeWidth={2.5}
          strokeLinecap="round"
        />

        {/* Quarter-hour labels */}
        {[0, 6, 12, 18].map((hour) => {
          const angle = angleFor(hour);
          return (
            <text
              key={hour}
              x={center + Math.cos(angle) * (outerRadius + 12)}
              y={center + Math.sin(angle) * (outerRadius + 12)}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={10}
              fill={TEXT.muted}
            >
              {String(hour).padStart(2, '0')}
            </text>
          );
        })}

        {/* Centre readout */}
        <text
          x={center}
          y={center - 4}
          textAnchor="middle"
          fontSize={20}
          fontWeight={600}
          fill={ACCENT.strong}
        >
          {formatHourOfDay(peakHourLocal)}
        </text>
        <text
          x={center}
          y={center + 12}
          textAnchor="middle"
          fontSize={10}
          fill={TEXT.muted}
        >
          local peak
        </text>
      </svg>

      <figcaption className="text-caption text-ink-secondary">
        Peaks at {formatHourOfDay(peakHourLocal)} local, not midday — this changes
        where shade must go.
      </figcaption>
    </figure>
  );
}
