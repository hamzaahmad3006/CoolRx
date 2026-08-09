'use client';

import {
  Area,
  AreaChart,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from 'recharts';

import { HEAT_SCALE, SURFACE, TEXT } from '@/constants';

interface DistributionPoint {
  readonly temperature: number;
  readonly density: number;
}

interface DistributionChartProps {
  /** From the API's `Normal_temperature_distribution` (x_axis / y_axis). */
  readonly points: readonly DistributionPoint[];
  /** Danger threshold, marked with a labelled rule. */
  readonly thresholdC: number;
  readonly height?: number;
}

/**
 * District temperature distribution with the danger threshold marked.
 *
 * Data comes straight from FortyGuard's own `stats_data`, not recomputed
 * locally, so the curve matches what their dashboard would show (SRS FR-004).
 * Axes are always labelled with units; no dual axes (SRS §28.6).
 */
export function DistributionChart({
  points,
  thresholdC,
  height = 160,
}: DistributionChartProps) {
  const fill = HEAT_SCALE[3] ?? '#f1605d';

  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={points as DistributionPoint[]}
          margin={{ top: 8, right: 8, bottom: 4, left: 0 }}
        >
          <defs>
            <linearGradient id="distFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={fill} stopOpacity={0.35} />
              <stop offset="100%" stopColor={fill} stopOpacity={0.04} />
            </linearGradient>
          </defs>

          <XAxis
            dataKey="temperature"
            type="number"
            domain={['dataMin', 'dataMax']}
            tickLine={false}
            axisLine={{ stroke: SURFACE.border }}
            tick={{ fill: TEXT.secondary, fontSize: 12 }}
            tickFormatter={(value: number) => `${value.toFixed(0)}°`}
            label={{
              value: 'Temperature (°C)',
              position: 'insideBottomRight',
              offset: -2,
              fill: TEXT.muted,
              fontSize: 11,
            }}
          />
          <YAxis hide />

          <Area
            type="monotone"
            dataKey="density"
            stroke={fill}
            strokeWidth={1.5}
            fill="url(#distFill)"
            isAnimationActive={false}
            dot={false}
          />

          <ReferenceLine
            x={thresholdC}
            stroke={TEXT.primary}
            strokeDasharray="3 3"
            strokeWidth={1}
            label={{
              value: `${thresholdC} °C threshold`,
              position: 'insideTopRight',
              fill: TEXT.secondary,
              fontSize: 11,
            }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
