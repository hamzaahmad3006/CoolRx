'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { BRAND, SHELL, type IconName } from '@/constants';
import { cn } from '@/lib/cn';
import { Icon } from '@/components/ui/Icon';

export interface RailItem {
  readonly label: string;
  readonly icon: IconName;
  /**
   * `null` when the destination does not exist yet — the plan pages are
   * plan-scoped, so they are unreachable until a plan has been generated. A dead
   * link here would 404 in front of whoever is being shown the tool.
   */
  readonly href: string | null;
  /** Shown as a tooltip explaining why an item is unavailable. */
  readonly unavailableReason?: string;
}

interface LeftRailProps {
  readonly projectId: string;
  /** Null until a plan has been generated for this project. */
  readonly planId?: string | null;
  readonly districtName: string;
  readonly districtContext: string;
  readonly collapsed?: boolean;
}

/**
 * Persistent left navigation. Active item carries a 2px accent bar plus a tinted
 * background — never colour alone (SRS §28.2).
 */
const NEEDS_PLAN = 'Generate a plan first';

/**
 * Rail destinations.
 *
 * The last four are **plan-scoped, not project-scoped** — the SRS routes them
 * under `/plans/[planId]` because a project can have several plans and a report
 * belongs to one of them. They are therefore unreachable until a plan exists, and
 * are rendered disabled rather than linked somewhere that 404s.
 */
export function buildRailItems(
  projectId: string,
  planId: string | null = null,
): readonly RailItem[] {
  return [
    { label: 'Diagnosis', icon: 'diagnosis', href: `/p/${projectId}/diagnose` },
    { label: 'Prescription', icon: 'prescription', href: `/p/${projectId}/prescribe` },
    { label: 'Before/After', icon: 'beforeAfter', href: `/p/${projectId}/compare` },
    { label: 'Impact & Equity', icon: 'impactEquity', href: `/p/${projectId}/equity` },
    {
      label: 'Action Plan',
      icon: 'actionPlan',
      href: planId === null ? null : `/plans/${planId}`,
      unavailableReason: NEEDS_PLAN,
    },
    {
      label: 'Verify',
      icon: 'verify',
      href: planId === null ? null : `/plans/${planId}/verify`,
      unavailableReason: NEEDS_PLAN,
    },
    {
      label: 'Agent Trace',
      icon: 'agentTrace',
      href: planId === null ? null : `/trace/${planId}`,
      unavailableReason: NEEDS_PLAN,
    },
    { label: 'Methods', icon: 'methods', href: '/methods' },
  ];
}

export function LeftRail({
  projectId,
  planId = null,
  districtName,
  districtContext,
  collapsed = false,
}: LeftRailProps) {
  const pathname = usePathname();
  const items = buildRailItems(projectId, planId);
  const width = collapsed ? SHELL.railWidthCollapsed : SHELL.railWidth;

  return (
    <nav
      aria-label="Analysis sections"
      className="flex shrink-0 flex-col border-r border-line bg-card"
      style={{ width }}
    >
      {/* Brand */}
      <div className="flex flex-col gap-0.5 px-4 py-4">
        <Link
          href="/"
          className="text-heading font-semibold text-accent-strong transition-colors hover:text-accent"
        >
          {collapsed ? 'Rx' : BRAND.name}
        </Link>
        {!collapsed ? (
          <p className="text-caption text-ink-muted">District context</p>
        ) : null}
      </div>

      {/* Navigation */}
      <ul className="flex flex-1 flex-col gap-0.5 px-2">
        {items.map((item) => {
          const active = item.href !== null && pathname === item.href;
          const shared = cn(
            'flex items-center gap-2.5 rounded-sharp px-2.5 py-2 text-body transition-colors',
            'border-l-2',
          );

          // Rendered as a non-interactive item rather than a link. `aria-disabled`
          // keeps it in the reading order so a screen-reader user learns the
          // section exists and why it is not yet available.
          if (item.href === null) {
            return (
              <li key={item.label}>
                <span
                  aria-disabled="true"
                  title={
                    collapsed
                      ? `${item.label} — ${item.unavailableReason ?? 'unavailable'}`
                      : item.unavailableReason
                  }
                  className={cn(
                    shared,
                    'cursor-not-allowed border-l-transparent text-ink-muted',
                  )}
                >
                  <Icon name={item.icon} size={16} />
                  {!collapsed ? <span className="truncate">{item.label}</span> : null}
                </span>
              </li>
            );
          }

          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? 'page' : undefined}
                title={collapsed ? item.label : undefined}
                className={cn(
                  shared,
                  active
                    ? 'border-l-accent bg-accent-subtle font-medium text-accent'
                    : 'border-l-transparent text-ink hover:bg-subtle',
                )}
              >
                <Icon name={item.icon} size={16} />
                {!collapsed ? <span className="truncate">{item.label}</span> : null}
              </Link>
            </li>
          );
        })}
      </ul>

      {/* District footer */}
      {!collapsed ? (
        <div className="border-t border-line px-4 py-3">
          <p className="truncate text-caption font-medium text-ink">{districtName}</p>
          <p className="truncate font-mono text-caption text-ink-muted" data-numeric>
            {districtContext}
          </p>
        </div>
      ) : null}
    </nav>
  );
}
