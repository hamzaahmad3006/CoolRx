import type { ReactNode } from 'react';

import type { IconName } from '@/constants';
import { cn } from '@/lib/cn';
import { Icon } from './Icon';
import { ProvenanceLink } from './Badges';

interface StatTileProps {
  readonly label: string;
  readonly icon?: IconName;
  /**
   * The value. Pass a plain formatted string for a MEASURED value, or an
   * `<Estimate />` element for a PREDICTED one — never a bare number for a
   * prediction (SRS §20.3).
   */
  readonly children: ReactNode;
  /** Secondary line beneath the value. */
  readonly detail?: string;
  readonly onShowProvenance?: () => void;
  readonly activityId?: string | null;
  readonly className?: string;
}

/**
 * Headline figure tile. Every tile presenting a derived number carries a
 * provenance affordance (SRS §20.2).
 */
export function StatTile({
  label,
  icon,
  children,
  detail,
  onShowProvenance,
  activityId,
  className,
}: StatTileProps) {
  return (
    <div
      className={cn(
        'flex flex-col gap-2 rounded-sharp border border-line bg-card p-5',
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5">
          {icon !== undefined ? (
            <Icon name={icon} size={14} className="text-ink-muted" />
          ) : null}
          <p className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
            {label}
          </p>
        </div>

        {onShowProvenance !== undefined ? (
          <ProvenanceLink onClick={onShowProvenance} activityId={activityId} />
        ) : null}
      </div>

      <div className="text-title font-semibold text-accent-strong" data-numeric>
        {children}
      </div>

      {detail !== undefined ? (
        <p className="text-caption text-ink-secondary">{detail}</p>
      ) : null}
    </div>
  );
}
