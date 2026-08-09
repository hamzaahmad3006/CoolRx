'use client';

import { cn } from '@/lib/cn';

export interface SegmentOption<TValue extends string> {
  readonly value: TValue;
  readonly label: string;
  readonly title?: string;
}

interface SegmentedControlProps<TValue extends string> {
  readonly options: readonly SegmentOption<TValue>[];
  readonly value: TValue;
  readonly onChange: (value: TValue) => void;
  readonly label: string;
  readonly className?: string;
}

/**
 * Segmented control — used for the objective selector and the map layer switch.
 * Implemented as a radio group so keyboard and screen-reader behaviour are
 * correct without custom key handling.
 */
export function SegmentedControl<TValue extends string>({
  options,
  value,
  onChange,
  label,
  className,
}: SegmentedControlProps<TValue>) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn(
        'inline-flex h-9 items-stretch overflow-hidden rounded-sharp border border-line bg-card',
        className,
      )}
    >
      {options.map((option, index) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            title={option.title}
            onClick={() => onChange(option.value)}
            className={cn(
              'px-3 text-caption transition-colors',
              index > 0 && 'border-l border-line',
              selected
                ? 'bg-accent-subtle font-medium text-accent'
                : 'text-ink hover:bg-subtle',
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
