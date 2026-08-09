'use client';

import { SHELL } from '@/constants';
import { cn } from '@/lib/cn';
import type { DataMode } from '@/types';
import { CreditChip, DataModeBadge } from '@/components/ui/Badges';
import { Icon } from '@/components/ui/Icon';
import { Tooltip } from '@/components/ui/Tooltip';

interface TopBarProps {
  /** Breadcrumb segments, e.g. ['Phoenix · Encanto', 'Prescribe']. */
  readonly breadcrumb: readonly string[];
  readonly dataMode: DataMode;
  readonly creditsRemaining: number | null;
  readonly creditReserve: number;
  readonly onToggleTheme: () => void;
  readonly isDark: boolean;
  readonly className?: string;
}

export function TopBar({
  breadcrumb,
  dataMode,
  creditsRemaining,
  creditReserve,
  onToggleTheme,
  isDark,
  className,
}: TopBarProps) {
  return (
    <header
      className={cn(
        'flex shrink-0 items-center justify-between gap-4 border-b border-line bg-card px-6',
        className,
      )}
      style={{ height: SHELL.topBarHeight }}
    >
      {/* Breadcrumb */}
      <nav aria-label="Breadcrumb" className="min-w-0">
        <ol className="flex items-center gap-2 text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
          {breadcrumb.map((segment, index) => (
            <li key={segment} className="flex items-center gap-2 truncate">
              {index > 0 ? (
                <span aria-hidden className="text-ink-muted">
                  /
                </span>
              ) : null}
              <span
                className={cn(
                  'truncate',
                  index === breadcrumb.length - 1 && 'text-ink',
                )}
              >
                {segment}
              </span>
            </li>
          ))}
        </ol>
      </nav>

      {/* Status cluster */}
      <div className="flex shrink-0 items-center gap-3">
        <DataModeBadge mode={dataMode} />
        <CreditChip remaining={creditsRemaining} reserve={creditReserve} />

        <span aria-hidden className="h-5 w-px bg-line" />

        <Tooltip content="Methods, model performance and limitations" side="bottom">
          <a
            href="/methods"
            className="rounded-sharp p-1.5 text-ink-muted transition-colors hover:bg-subtle hover:text-accent"
          >
            <Icon name="help" size={16} label="Methods and limitations" />
          </a>
        </Tooltip>

        <Tooltip content={isDark ? 'Switch to light theme' : 'Switch to dark theme'} side="bottom">
          <button
            type="button"
            onClick={onToggleTheme}
            className="rounded-sharp p-1.5 text-ink-muted transition-colors hover:bg-subtle hover:text-accent"
          >
            <Icon
              name={isDark ? 'lightMode' : 'darkMode'}
              size={16}
              label="Toggle theme"
            />
          </button>
        </Tooltip>
      </div>
    </header>
  );
}
