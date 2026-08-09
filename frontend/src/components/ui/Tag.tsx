import type { ReactNode } from 'react';

import { INTERVENTION_COLORS, type InterventionCategory } from '@/constants';
import { cn } from '@/lib/cn';

export type TagVariant =
  | 'neutral'
  | 'accent'
  | 'caution'
  | 'danger'
  | 'verified';

interface TagProps {
  readonly variant?: TagVariant;
  /** Renders a category colour dot instead of a variant fill. */
  readonly category?: InterventionCategory;
  readonly children: ReactNode;
  readonly className?: string;
}

/**
 * 20px chip, 4px radius, hairline border of its own hue at ~10% background
 * opacity (SRS §28.5). Never pill-shaped — Stitch's output used `rounded-full`
 * in 35 places; this is the corrected baseline.
 */
const VARIANT_CLASSES: Readonly<Record<TagVariant, string>> = {
  neutral: 'border-line bg-subtle text-ink-secondary',
  accent: 'border-accent/30 bg-accent-subtle text-accent',
  caution: 'border-caution-line bg-caution-bg text-caution',
  danger: 'border-danger-line bg-danger-bg text-danger',
  verified: 'border-verified-line bg-verified-bg text-verified',
};

export function Tag({
  variant = 'neutral',
  category,
  children,
  className,
}: TagProps) {
  return (
    <span
      className={cn(
        'inline-flex h-5 items-center gap-1.5 rounded-sharp border px-1.5',
        'text-eyebrow font-medium whitespace-nowrap',
        category === undefined
          ? VARIANT_CLASSES[variant]
          : 'border-line bg-card text-ink-secondary',
        className,
      )}
    >
      {category !== undefined ? (
        <span
          aria-hidden
          className="size-2 shrink-0 rounded-[2px]"
          style={{ backgroundColor: INTERVENTION_COLORS[category] }}
        />
      ) : null}
      {children}
    </span>
  );
}
