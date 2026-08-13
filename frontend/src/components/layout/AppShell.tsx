'use client';

import type { ReactNode } from 'react';

import { SHELL } from '@/constants';
import { cn } from '@/lib/cn';
import { useAppDispatch, useAppSelector } from '@/redux/hooks';
import { toggleTheme } from '@/redux/slices/uiSlice';
import { DegradedBanner, type DegradedReason } from '@/components/feedback/States';
import { LeftRail } from './LeftRail';
import { TopBar } from './TopBar';

interface AppShellProps {
  readonly projectId: string;
  readonly districtName: string;
  readonly districtContext: string;
  readonly breadcrumb: readonly string[];
  /** Optional right analysis panel. Omit for full-width pages (plan table). */
  readonly panel?: ReactNode;
  readonly children: ReactNode;
  /** Set when the app is serving cached/fixture data or credits are low. */
  readonly degradedReason?: DegradedReason | null;
  readonly creditsRemaining?: number | null;
  readonly creditReserve?: number;
  /** Full-width layouts scroll the whole main area rather than a map canvas. */
  readonly scrollMain?: boolean;
}

/**
 * Persistent application chrome: left rail, top bar, optional degraded banner,
 * main canvas and optional right panel (SRS §28.4).
 *
 * Theme and rail-collapse state come from the UI slice so they survive
 * navigation between screens.
 */
export function AppShell({
  projectId,
  districtName,
  districtContext,
  breadcrumb,
  panel,
  children,
  degradedReason = null,
  creditsRemaining = null,
  creditReserve = 50_000,
  scrollMain = false,
}: AppShellProps) {
  const dispatch = useAppDispatch();
  const theme = useAppSelector((state) => state.ui.theme);
  const railCollapsed = useAppSelector((state) => state.ui.railCollapsed);
  const dataMode = useAppSelector((state) => state.session.dataMode);
  // Plan-scoped rail entries stay disabled until a plan exists, rather than
  // linking to a route that cannot resolve.
  const currentPlanId = useAppSelector((state) => state.session.currentPlanId);

  const isDark = theme === 'dark';

  return (
    <div className={cn('flex h-screen overflow-hidden bg-canvas', isDark && 'dark')}>
      <LeftRail
        projectId={projectId}
        planId={currentPlanId}
        districtName={districtName}
        districtContext={districtContext}
        collapsed={railCollapsed}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          breadcrumb={breadcrumb}
          dataMode={dataMode}
          creditsRemaining={creditsRemaining}
          creditReserve={creditReserve}
          onToggleTheme={() => dispatch(toggleTheme())}
          isDark={isDark}
        />

        {degradedReason !== null ? <DegradedBanner reason={degradedReason} /> : null}

        <div className="flex min-h-0 flex-1">
          <main
            className={cn(
              'min-w-0 flex-1',
              scrollMain ? 'overflow-y-auto p-6' : 'relative overflow-hidden',
            )}
          >
            {children}
          </main>

          {panel !== undefined ? (
            <aside
              className="shrink-0 overflow-y-auto border-l border-line bg-canvas p-5"
              style={{ width: SHELL.panelWidth }}
            >
              {panel}
            </aside>
          ) : null}
        </div>
      </div>
    </div>
  );
}
