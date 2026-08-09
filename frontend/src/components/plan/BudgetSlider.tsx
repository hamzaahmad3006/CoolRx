'use client';

import { GLOSSARY } from '@/constants';
import { formatCurrency, formatCurrencyCompact } from '@/lib/format';
import { cn } from '@/lib/cn';
import { Tooltip } from '@/components/ui/Tooltip';

interface BudgetSliderProps {
  readonly value: number;
  readonly onChange: (value: number) => void;
  readonly min?: number;
  readonly max?: number;
  readonly step?: number;
  readonly className?: string;
}

const PRESETS: readonly number[] = [250_000, 500_000, 1_000_000];

/**
 * Budget control: slider with a value bubble, an exact numeric input, and preset
 * step buttons. The exact input exists because a planner works from a real
 * appropriation figure, not an approximate drag.
 */
export function BudgetSlider({
  value,
  onChange,
  min = 50_000,
  max = 2_000_000,
  step = 10_000,
  className,
}: BudgetSliderProps) {
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <div className="flex items-baseline justify-between gap-3">
        <label
          htmlFor="budget-slider"
          className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary"
        >
          Budget limit
        </label>
        <span className="font-mono text-body font-medium text-ink" data-numeric>
          {formatCurrency(value)}
        </span>
      </div>

      <input
        id="budget-slider"
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-valuetext={formatCurrency(value)}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-[2px] bg-inset accent-accent"
      />

      <div className="flex items-center gap-2">
        {PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            onClick={() => onChange(preset)}
            className={cn(
              'rounded-sharp border px-2 py-0.5 font-mono text-eyebrow transition-colors',
              preset === value
                ? 'border-accent/30 bg-accent-subtle text-accent'
                : 'border-line text-ink-secondary hover:bg-subtle',
            )}
          >
            {formatCurrencyCompact(preset)}
          </button>
        ))}

        <Tooltip content={GLOSSARY.marginalBenefit} side="bottom">
          <input
            type="number"
            min={min}
            max={max}
            step={step}
            value={value}
            onChange={(event) => onChange(Number(event.target.value))}
            aria-label="Exact budget in US dollars"
            className="ml-auto w-28 rounded-sharp border border-line bg-card px-2 py-0.5 text-right font-mono text-caption text-ink"
          />
        </Tooltip>
      </div>
    </div>
  );
}
