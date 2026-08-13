'use client';

import { LAND_COVER_COLORS } from '@/constants';
import { formatNumber } from '@/lib/format';
import type { TileFeatures } from '@/types';

interface LandCoverDonutProps {
  readonly features: TileFeatures;
  readonly size?: number;
}

interface Slice {
  readonly key: string;
  readonly label: string;
  readonly pct: number;
  readonly color: string;
  readonly measured: boolean;
}

/**
 * Land-cover composition for one tile.
 *
 * Inline SVG rather than a chart library: this is five arcs, and hand-drawing
 * them keeps full control over the one behaviour that matters here — what happens
 * when the percentages do not add to 100.
 *
 * They frequently will not. NLCD has genuine gaps, so a tile can have canopy and
 * water measured and the rest unknown. The remainder is drawn as an explicitly
 * hatched "unmeasured" arc rather than being normalised away or absorbed into
 * `impervious`. Normalising would invent composition data, which SRS FR-008
 * forbids: the whole point of a driver chart is that a planner can trust what it
 * says the ground is made of.
 */
export function LandCoverDonut({ features, size = 132 }: LandCoverDonutProps) {
  const slices = buildSlices(features);
  const measuredTotal = slices
    .filter((s) => s.measured)
    .reduce((sum, s) => sum + s.pct, 0);

  // Whatever is left over is unmeasured, never redistributed.
  const unknownPct = Math.max(0, 100 - measuredTotal);
  const all: Slice[] =
    unknownPct > 0.5
      ? [
          ...slices,
          {
            key: 'unknown',
            label: 'Not measured',
            pct: unknownPct,
            color: LAND_COVER_COLORS.unknown,
            measured: false,
          },
        ]
      : slices;

  if (all.length === 0) {
    return (
      <p className="text-sm text-ink-secondary">
        Land cover is unavailable for this block.
      </p>
    );
  }

  const radius = size / 2;
  const stroke = size * 0.18;
  const inner = radius - stroke / 2;
  const circumference = 2 * Math.PI * inner;

  let offset = 0;

  return (
    <div className="flex items-center gap-4">
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={describe(all)}
      >
        <defs>
          {/* Hatching, so "not measured" is distinguishable without colour. */}
          <pattern
            id="lc-unmeasured"
            width="6"
            height="6"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <rect width="6" height="6" fill={LAND_COVER_COLORS.unknown} />
            <line x1="0" y1="0" x2="0" y2="6" stroke="#FFFFFF" strokeWidth="2.5" />
          </pattern>
        </defs>

        <g transform={`rotate(-90 ${radius} ${radius})`}>
          {all.map((slice) => {
            const length = (slice.pct / 100) * circumference;
            const element = (
              <circle
                key={slice.key}
                cx={radius}
                cy={radius}
                r={inner}
                fill="none"
                stroke={slice.measured ? slice.color : 'url(#lc-unmeasured)'}
                strokeWidth={stroke}
                strokeDasharray={`${length} ${circumference - length}`}
                strokeDashoffset={-offset}
              />
            );
            offset += length;
            return element;
          })}
        </g>
      </svg>

      <ul className="flex min-w-0 flex-col gap-1">
        {all.map((slice) => (
          <li key={slice.key} className="flex items-center gap-2 text-xs">
            <span
              aria-hidden="true"
              className="size-2.5 shrink-0 rounded-[2px]"
              style={{
                backgroundColor: slice.color,
                // Dashed edge repeats the hatch cue at legend scale, where a
                // 10px swatch is too small to show the pattern itself.
                outline: slice.measured ? 'none' : `1px dashed ${LAND_COVER_COLORS.building}`,
              }}
            />
            <span className="truncate text-ink-secondary">{slice.label}</span>
            <span className="ml-auto tabular-nums text-ink-primary" data-numeric>
              {formatNumber(slice.pct, 'count')}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Only measured components become slices. `null` is skipped, never zeroed. */
function buildSlices(features: TileFeatures): Slice[] {
  const candidates: readonly {
    key: string;
    label: string;
    value: number | null;
    color: string;
  }[] = [
    { key: 'canopy', label: 'Tree canopy', value: features.canopyPct, color: LAND_COVER_COLORS.canopy },
    { key: 'grass', label: 'Grass and shrub', value: features.grassShrubPct, color: LAND_COVER_COLORS.grassShrub },
    { key: 'water', label: 'Water', value: features.waterPct, color: LAND_COVER_COLORS.water },
    { key: 'building', label: 'Buildings', value: features.buildingPct, color: LAND_COVER_COLORS.building },
    { key: 'impervious', label: 'Other paved', value: features.imperviousPct, color: LAND_COVER_COLORS.impervious },
  ];

  return candidates
    .filter((c): c is typeof c & { value: number } => c.value !== null && c.value > 0)
    .map((c) => ({
      key: c.key,
      label: c.label,
      pct: c.value,
      color: c.color,
      measured: true,
    }));
}

function describe(slices: readonly Slice[]): string {
  return `Land cover: ${slices
    .map((s) => `${s.label} ${s.pct.toFixed(0)}%`)
    .join(', ')}`;
}
