'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { BRAND, SHELL, type IconName } from '@/constants';
import { cn } from '@/lib/cn';
import { Icon } from '@/components/ui/Icon';

export interface RailItem {
  readonly label: string;
  readonly icon: IconName;
  readonly href: string;
}

interface LeftRailProps {
  readonly projectId: string;
  readonly districtName: string;
  readonly districtContext: string;
  readonly collapsed?: boolean;
}

/**
 * Persistent left navigation. Active item carries a 2px accent bar plus a tinted
 * background — never colour alone (SRS §28.2).
 */
export function buildRailItems(projectId: string): readonly RailItem[] {
  return [
    { label: 'Diagnosis', icon: 'diagnosis', href: `/p/${projectId}/diagnose` },
    { label: 'Priorities', icon: 'priorities', href: `/p/${projectId}/priorities` },
    { label: 'Prescription', icon: 'prescription', href: `/p/${projectId}/prescribe` },
    { label: 'Before/After', icon: 'beforeAfter', href: `/p/${projectId}/compare` },
    { label: 'Impact & Equity', icon: 'impactEquity', href: `/p/${projectId}/equity` },
    { label: 'Action Plan', icon: 'actionPlan', href: `/p/${projectId}/plan` },
    { label: 'Verify', icon: 'verify', href: `/p/${projectId}/verify` },
    { label: 'Agent Trace', icon: 'agentTrace', href: `/p/${projectId}/trace` },
    { label: 'Methods', icon: 'methods', href: '/methods' },
  ];
}

export function LeftRail({
  projectId,
  districtName,
  districtContext,
  collapsed = false,
}: LeftRailProps) {
  const pathname = usePathname();
  const items = buildRailItems(projectId);
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
          const active = pathname === item.href;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? 'page' : undefined}
                title={collapsed ? item.label : undefined}
                className={cn(
                  'flex items-center gap-2.5 rounded-sharp px-2.5 py-2 text-body transition-colors',
                  'border-l-2',
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
