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
        // `min-h-9`, not `h-9`. A fixed height with `overflow-hidden` cropped
        // any label that wrapped: "Max people-hours" and "Equity weighted" lost
        // their second line mid-word, leaving three buttons a viewer could not
        // read. The labels no longer wrap, so the row keeps its height in
        // practice — the minimum is there for the case where they must.
        'inline-flex min-h-9 items-stretch overflow-hidden rounded-sharp border border-line bg-card',
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
              'whitespace-nowrap px-3 text-caption transition-colors',
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
