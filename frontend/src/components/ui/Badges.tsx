import { RISK_COLORS, type IconName, type RiskLevel } from '@/constants';
import { formatNumber } from '@/lib/format';
import { cn } from '@/lib/cn';
import type { DataMode, JobStatus } from '@/types';
import { Icon } from './Icon';
import { Tag } from './Tag';
import { Tooltip } from './Tooltip';

/* ═════════════════════════════════════════════════════════════════════════════
 * RISK BADGE
 *
 * SRS §28.7: a risk level is ALWAYS colour + icon + word. Colour alone is never
 * sufficient — it fails for colour-blind users and in greyscale print.
 * ════════════════════════════════════════════════════════════════════════════*/
const RISK_LABEL: Readonly<Record<RiskLevel, string>> = {
  low: 'Low',
  moderate: 'Moderate',
  high: 'High',
  extreme: 'Extreme',
};

const RISK_ICON: Readonly<Record<RiskLevel, IconName>> = {
  low: 'riskLow',
  moderate: 'riskModerate',
  high: 'riskHigh',
  extreme: 'riskExtreme',
};

export function RiskBadge({ level }: { readonly level: RiskLevel }) {
  const color = RISK_COLORS[level];

  return (
    <span
      className="inline-flex h-5 items-center gap-1.5 rounded-sharp border px-1.5 text-eyebrow font-medium"
      style={{
        color,
        borderColor: `${color}4D`, // ~30% alpha
        backgroundColor: `${color}1A`, // ~10% alpha
      }}
    >
      <Icon name={RISK_ICON[level]} size={12} />
      {RISK_LABEL[level]}
    </span>
  );
}

/* ═════════════════════════════════════════════════════════════════════════════
 * DATA MODE BADGE
 *
 * Always visible in the top bar. Fixture data must be impossible to mistake for
 * live data (SRS FR-022).
 * ════════════════════════════════════════════════════════════════════════════*/
const DATA_MODE: Readonly<
  Record<DataMode, { label: string; icon: IconName; tooltip: string }>
> = {
  live: {
    label: 'Live',
    icon: 'complete',
    tooltip: 'Measurements fetched from the temperature API.',
  },
  cached: {
    label: 'Cached',
    icon: 'cached',
    tooltip: 'Showing previously fetched measurements for this district.',
  },
  fixture: {
    label: 'Fixture data',
    icon: 'fixture',
    tooltip:
      'This instance runs from committed fixtures — no live API calls are made.',
  },
};

export function DataModeBadge({ mode }: { readonly mode: DataMode }) {
  const config = DATA_MODE[mode];
  const variant = mode === 'cached' ? 'caution' : 'neutral';

  return (
    <Tooltip content={config.tooltip} side="bottom">
      <Tag variant={variant} className="cursor-help">
        <Icon name={config.icon} size={12} />
        {config.label}
      </Tag>
    </Tooltip>
  );
}

/* ═════════════════════════════════════════════════════════════════════════════
 * CREDIT CHIP
 * ════════════════════════════════════════════════════════════════════════════*/
interface CreditChipProps {
  /** `null` when the credits endpoint could not be resolved (see SRS C-10). */
  readonly remaining: number | null;
  readonly reserve: number;
}

export function CreditChip({ remaining, reserve }: CreditChipProps) {
  const belowReserve = remaining !== null && remaining <= reserve;
  const label = remaining === null ? 'unknown' : formatNumber(remaining, 'count');

  return (
    <Tooltip
      content={
        remaining === null
          ? 'Credit balance could not be read; a local counter is used instead.'
          : `Reserve floor: ${formatNumber(reserve, 'count')}. Live analysis pauses below it.`
      }
      side="bottom"
    >
      <Tag variant={belowReserve ? 'caution' : 'neutral'} className="cursor-help font-mono">
        <Icon name="credits" size={12} />
        {label}
      </Tag>
    </Tooltip>
  );
}

/* ═════════════════════════════════════════════════════════════════════════════
 * STATUS PILL — job lifecycle
 * ════════════════════════════════════════════════════════════════════════════*/
const JOB_STATUS: Readonly<
  Record<JobStatus, { label: string; icon: IconName; variant: 'neutral' | 'accent' | 'caution' | 'danger' | 'verified' }>
> = {
  queued: { label: 'Queued', icon: 'queued', variant: 'neutral' },
  running: { label: 'Running', icon: 'running', variant: 'accent' },
  completed: { label: 'Complete', icon: 'complete', variant: 'verified' },
  failed: { label: 'Failed', icon: 'failed', variant: 'danger' },
  degraded: { label: 'Cached', icon: 'cached', variant: 'caution' },
};

interface StatusPillProps {
  readonly status: JobStatus;
  /** Current pipeline stage, shown alongside the status when running. */
  readonly stage?: string | null;
}

export function StatusPill({ status, stage }: StatusPillProps) {
  const config = JOB_STATUS[status];

  return (
    <Tag variant={config.variant}>
      <Icon
        name={config.icon}
        size={12}
        className={status === 'running' ? 'animate-spin' : undefined}
      />
      {config.label}
      {stage !== undefined && stage !== null && status === 'running' ? (
        <span className="font-normal text-ink-secondary">· {stage}</span>
      ) : null}
    </Tag>
  );
}

/* ═════════════════════════════════════════════════════════════════════════════
 * PROVENANCE LINK
 *
 * SRS §20.2: every derived figure must be traceable. This is the affordance that
 * exposes it — present beside every headline number.
 * ════════════════════════════════════════════════════════════════════════════*/
interface ProvenanceLinkProps {
  readonly onClick: () => void;
  /** FortyGuard activity handle, when the figure derives from a measurement. */
  readonly activityId?: string | null;
  readonly className?: string;
}

export function ProvenanceLink({
  onClick,
  activityId,
  className,
}: ProvenanceLinkProps) {
  const tooltip =
    activityId !== undefined && activityId !== null
      ? `Where this number came from · activity ${activityId}`
      : 'Where this number came from';

  return (
    <Tooltip content={tooltip} side="bottom">
      <button
        type="button"
        onClick={onClick}
        className={cn(
          'rounded-sharp p-1 text-ink-muted transition-colors',
          'hover:bg-subtle hover:text-accent',
          className,
        )}
      >
        <Icon name="provenance" size={14} label="Show provenance" />
      </button>
    </Tooltip>
  );
}
