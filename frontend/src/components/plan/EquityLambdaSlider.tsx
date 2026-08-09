'use client';

import { DISCLAIMER, GLOSSARY } from '@/constants';
import { cn } from '@/lib/cn';
import { Icon } from '@/components/ui/Icon';
import { Tooltip } from '@/components/ui/Tooltip';

interface EquityLambdaSliderProps {
  readonly value: number;
  readonly onChange: (value: number) => void;
  readonly className?: string;
}

/**
 * Equity weight (λ).
 *
 * Deliberately exposed rather than hidden inside a composite score. Prioritising
 * by vulnerability is a value judgement about how much extra weight it deserves,
 * so the parameter is surfaced, adjustable, and labelled as a policy choice
 * rather than a scientific constant (SRS §9.5.2). Burying a fixed weight would
 * be less honest and less useful.
 */
export function EquityLambdaSlider({
  value,
  onChange,
  className,
}: EquityLambdaSliderProps) {
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <div className="flex items-baseline justify-between gap-3">
        <label
          htmlFor="equity-lambda"
          className="flex items-center gap-1.5 text-eyebrow uppercase tracking-[0.08em] text-ink-secondary"
        >
          Equity weight (λ)
          <Tooltip content={GLOSSARY.equityWeight}>
            <span className="cursor-help text-ink-muted">
              <Icon name="info" size={12} />
            </span>
          </Tooltip>
        </label>
        <span className="font-mono text-body font-medium text-ink" data-numeric>
          {value.toFixed(1)}
        </span>
      </div>

      <input
        id="equity-lambda"
        type="range"
        min={0}
        max={2}
        step={0.1}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-valuetext={`Equity weight ${value.toFixed(1)}`}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-[2px] bg-inset accent-accent"
      />

      <p className="text-caption text-ink-muted">{DISCLAIMER.equityLambda}</p>
    </div>
  );
}
