'use client';

import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from 'recharts';

import { SURFACE, TEXT } from '@/constants';
import { coolingColor } from '@/lib/scale';

interface DeltaBin {
  readonly deltaC: number;
  readonly count: number;
}

interface DeltaHistogramProps {
  readonly bins: readonly DeltaBin[];
  /** Maximum absolute ΔT, so cooling and warming are equally saturated. */
  readonly maxAbsDelta: number;
  readonly height?: number;
}

/**
 * Distribution of predicted temperature change across treated blocks.
 *
 * Bars use the diverging cooling ramp — a different hue family from the heat
 * scale, so "cooled" can never be confused with "hot" (SRS §28.2). Zero is
 * marked explicitly because the sign is the whole point.
 */
export function DeltaHistogram({
  bins,
  maxAbsDelta,
  height = 150,
}: DeltaHistogramProps) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={bins as DeltaBin[]}
          margin={{ top: 8, right: 8, bottom: 4, left: 0 }}
        >
          <XAxis
            dataKey="deltaC"
            tickLine={false}
            axisLine={{ stroke: SURFACE.border }}
            tick={{ fill: TEXT.secondary, fontSize: 12 }}
            tickFormatter={(value: number) => value.toFixed(1)}
            label={{
              value: 'Predicted change (°C)',
              position: 'insideBottomRight',
              offset: -2,
              fill: TEXT.muted,
              fontSize: 11,
            }}
          />
          <YAxis hide />

          <ReferenceLine x={0} stroke={TEXT.primary} strokeWidth={1} />

          <Bar dataKey="count" isAnimationActive={false}>
            {bins.map((bin) => (
              <Cell
                key={bin.deltaC}
                fill={coolingColor(bin.deltaC, maxAbsDelta)}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
