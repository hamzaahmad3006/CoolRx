'use client';

import { BANNER, type IconName } from '@/constants';
import { cn } from '@/lib/cn';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';

/* ═════════════════════════════════════════════════════════════════════════════
 * EMPTY STATE
 *
 * Explains the state and offers the next action (SRS §27.4). Deliberately
 * icon-light — a big decorative glyph reads as a consumer app.
 * ════════════════════════════════════════════════════════════════════════════*/
interface EmptyStateProps {
  readonly message: string;
  readonly hint: string;
  readonly actionLabel?: string;
  readonly onAction?: () => void;
  readonly className?: string;
}

export function EmptyState({
  message,
  hint,
  actionLabel,
  onAction,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-start gap-2 rounded-sharp border border-dashed border-line bg-card p-6',
        className,
      )}
    >
      <p className="text-body font-medium text-ink">{message}</p>
      <p className="text-caption text-ink-secondary">{hint}</p>
      {actionLabel !== undefined && onAction !== undefined ? (
        <Button variant="secondary" onClick={onAction} className="mt-2">
          {actionLabel}
        </Button>
      ) : null}
    </div>
  );
}

/* ═════════════════════════════════════════════════════════════════════════════
 * ERROR STATE
 *
 * Plain language first, cause second, action third. The correlation ID is
 * copyable so a bug report is actionable. Never a stack trace (SRS §27.5).
 * ════════════════════════════════════════════════════════════════════════════*/
interface ErrorStateProps {
  readonly message: string;
  readonly hint: string;
  readonly correlationId?: string | null;
  readonly onRetry?: () => void;
  readonly className?: string;
}

export function ErrorState({
  message,
  hint,
  correlationId,
  onRetry,
  className,
}: ErrorStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-start gap-2 rounded-sharp border border-danger-line bg-danger-bg p-6',
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <Icon name="error" size={16} className="text-danger" />
        <p className="text-body font-medium text-danger">{message}</p>
      </div>
      <p className="text-caption text-ink-secondary">{hint}</p>

      {correlationId !== undefined && correlationId !== null ? (
        <p className="mt-1 font-mono text-caption text-ink-muted" data-numeric>
          Reference: {correlationId}
        </p>
      ) : null}

      {onRetry !== undefined ? (
        <Button variant="secondary" onClick={onRetry} icon="reset" className="mt-2">
          Retry
        </Button>
      ) : null}
    </div>
  );
}

/* ═════════════════════════════════════════════════════════════════════════════
 * DEGRADED BANNER
 *
 * Degraded is not an error — the product keeps working on cached data. Full
 * width beneath the top bar, amber, not dismissible while the condition holds.
 * ════════════════════════════════════════════════════════════════════════════*/
export type DegradedReason = 'degraded' | 'fixture' | 'creditsLow';

interface DegradedBannerProps {
  readonly reason: DegradedReason;
  readonly className?: string;
}

const REASON_ICON: Readonly<Record<DegradedReason, IconName>> = {
  degraded: 'cached',
  fixture: 'fixture',
  creditsLow: 'credits',
};

export function DegradedBanner({ reason, className }: DegradedBannerProps) {
  const isFixture = reason === 'fixture';

  return (
    <div
      role="status"
      className={cn(
        'flex items-center gap-2 border-b px-6 py-2 text-caption',
        isFixture
          ? 'border-line bg-subtle text-ink-secondary'
          : 'border-caution-line bg-caution-bg text-caution',
        className,
      )}
    >
      <Icon name={REASON_ICON[reason]} size={14} />
      {BANNER[reason]}
    </div>
  );
}

/* ═════════════════════════════════════════════════════════════════════════════
 * SKELETON
 *
 * Matches the final layout shape so there is no layout shift. Subtle pulse, no
 * shimmer sweep.
 * ════════════════════════════════════════════════════════════════════════════*/
interface SkeletonProps {
  readonly className?: string;
}

export function Skeleton({ className }: SkeletonProps) {
  return (
    <span
      aria-hidden
      className={cn('block animate-pulse rounded-sharp bg-inset', className)}
    />
  );
}

/* ═════════════════════════════════════════════════════════════════════════════
 * JOB PROGRESS
 *
 * FortyGuard tasks legitimately take minutes. A bare spinner is forbidden — the
 * user must always know which stage is running and how long it has taken
 * (SRS §27.3). Turning the platform's latency into an explanation of its depth
 * is deliberate.
 * ════════════════════════════════════════════════════════════════════════════*/
interface JobProgressProps {
  readonly stages: readonly string[];
  readonly currentStage: string | null;
  readonly progressPct: number;
  readonly elapsedS: number;
  /** Shown on first run to explain why this is not instant. */
  readonly showLatencyNote?: boolean;
  readonly className?: string;
}

export function JobProgress({
  stages,
  currentStage,
  progressPct,
  elapsedS,
  showLatencyNote = false,
  className,
}: JobProgressProps) {
  const currentIndex =
    currentStage === null ? -1 : stages.indexOf(currentStage);
  const stageNumber = currentIndex >= 0 ? currentIndex + 1 : 0;

  return (
    <div
      className={cn('flex flex-col gap-3 rounded-sharp border border-line bg-card p-5', className)}
      aria-live="polite"
    >
      <div className="flex items-baseline justify-between gap-4">
        <p className="text-body font-medium text-ink">
          {currentStage === null
            ? 'Preparing analysis…'
            : `${currentStage} (${stageNumber} of ${stages.length})`}
        </p>
        <p className="font-mono text-caption text-ink-secondary" data-numeric>
          {Math.round(elapsedS)}s
        </p>
      </div>

      {/* Progress track */}
      <div className="h-1.5 w-full overflow-hidden rounded-[2px] bg-inset">
        <div
          className="h-full bg-accent transition-[width] duration-300"
          style={{ width: `${Math.min(100, Math.max(0, progressPct))}%` }}
        />
      </div>

      {/* Stage list */}
      <ol className="flex flex-wrap gap-x-3 gap-y-1">
        {stages.map((stage, index) => {
          const done = currentIndex > index;
          const active = currentIndex === index;
          return (
            <li
              key={stage}
              className={cn(
                'flex items-center gap-1 text-caption',
                done && 'text-verified',
                active && 'text-accent font-medium',
                !done && !active && 'text-ink-muted',
              )}
            >
              {done ? <Icon name="complete" size={12} /> : null}
              {active ? <Icon name="running" size={12} className="animate-spin" /> : null}
              {stage}
            </li>
          );
        })}
      </ol>

      {showLatencyNote ? (
        <p className="text-caption text-ink-muted">
          The temperature API computes heatmaps as asynchronous tasks — typically
          one to three minutes per analytic. Results are cached, so re-running is
          instant.
        </p>
      ) : null}
    </div>
  );
}
