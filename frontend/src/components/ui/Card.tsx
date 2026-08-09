import type { ReactNode } from 'react';

import { Icon } from './Icon';
import { cn } from '@/lib/cn';

interface CardProps {
  /** Small-caps label above the title. */
  readonly eyebrow?: string;
  readonly title?: string;
  /** Renders a provenance affordance in the header when provided. */
  readonly onShowProvenance?: () => void;
  readonly actions?: ReactNode;
  readonly children: ReactNode;
  readonly className?: string;
  readonly bodyClassName?: string;
}

/**
 * Layer 1 surface: white fill, 1px hairline border, 4px radius, NO shadow.
 * Hierarchy comes from tonal layering and hairlines, never elevation
 * (SRS §28.5). Stitch's output drifted to `shadow-sm` in six places; this
 * component is the corrected baseline.
 */
export function Card({
  eyebrow,
  title,
  onShowProvenance,
  actions,
  children,
  className,
  bodyClassName,
}: CardProps) {
  const hasHeader =
    eyebrow !== undefined ||
    title !== undefined ||
    actions !== undefined ||
    onShowProvenance !== undefined;

  return (
    <section
      className={cn(
        'rounded-sharp border border-line bg-card',
        className,
      )}
    >
      {hasHeader ? (
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 pb-3 pt-4">
          <div className="min-w-0">
            {eyebrow !== undefined ? (
              <p className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
                {eyebrow}
              </p>
            ) : null}
            {title !== undefined ? (
              <h2 className="mt-1 truncate text-heading font-semibold text-accent-strong">
                {title}
              </h2>
            ) : null}
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {actions}
            {onShowProvenance !== undefined ? (
              <button
                type="button"
                onClick={onShowProvenance}
                title="Where this number came from"
                className="rounded-sharp p-1 text-ink-muted transition-colors hover:bg-subtle hover:text-accent"
              >
                <Icon name="provenance" label="Show provenance" />
              </button>
            ) : null}
          </div>
        </header>
      ) : null}

      <div className={cn('p-5', bodyClassName)}>{children}</div>
    </section>
  );
}
