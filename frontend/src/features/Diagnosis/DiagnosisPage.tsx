'use client';

import { ERROR_COPY, GLOSSARY } from '@/constants';
import {
  formatHourOfDayMaybe,
  formatNumber,
  formatNumberMaybe,
} from '@/lib/format';
import type { TilePriority } from '@/types';
import { AppShell } from '@/components/layout/AppShell';
import { DistributionChart } from '@/components/charts/DistributionChart';
import { PeakHourClock } from '@/components/charts/PeakHourClock';
import { MapLegend } from '@/components/map/MapLegend';
import { TileMap } from '@/components/map/TileMap';
import { ErrorState, Skeleton } from '@/components/feedback/States';
import { RiskBadge } from '@/components/ui/Badges';
import { Card } from '@/components/ui/Card';
import { type Column, DataTable } from '@/components/ui/DataTable';
import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { Tooltip } from '@/components/ui/Tooltip';
import { ANALYTIC_OPTIONS, useDiagnosis } from './useDiagnosis';

interface DiagnosisPageProps {
  readonly projectId: string;
  readonly districtName: string;
  readonly districtContext: string;
}

/**
 * Diagnosis — the core analysis screen.
 *
 * Built from the SRS §15.2 specification rather than a Stitch mockup (the Stitch
 * export for this screen was empty). It follows the same design language as the
 * other pages because that language now lives in `@/constants`.
 *
 * Four analytic layers, not one: temperature, heat dose, persistence and peak
 * hour. Most heat tools show only the first.
 */
export function DiagnosisPage({
  projectId,
  districtName,
  districtContext,
}: DiagnosisPageProps) {
  const {
    activeAnalytic,
    meta,
    tiles,
    domain,
    stats,
    priorities,
    peakHourHistogram,
    districtPeakHourLocal,
    tileCount,
    thresholdC,
    center,
    selectedTileKey,
    isLoading,
    errorMessage,
    distributionPoints,
    onAnalyticChange,
    onSelectTile,
  } = useDiagnosis({ projectId });

  const columns: readonly Column<TilePriority>[] = [
    {
      key: 'rank',
      header: '#',
      numeric: true,
      width: '3rem',
      render: (row) => String(row.rank).padStart(2, '0'),
    },
    {
      key: 'block',
      header: 'Block',
      width: '5.5rem',
      render: (row) => <span className="font-mono">{row.tileKey}</span>,
    },
    { key: 'risk', header: 'Risk', render: (row) => <RiskBadge level={row.riskLevel} /> },
    {
      key: 'exceedance',
      header: 'Hours',
      numeric: true,
      render: (row) => formatNumberMaybe(row.exceedanceHours, 'hour'),
    },
    {
      key: 'persistence',
      header: 'Unbroken',
      numeric: true,
      render: (row) => formatNumberMaybe(row.persistenceHours, 'hour'),
    },
    {
      key: 'peak',
      header: 'Peaks',
      numeric: true,
      hideOnNarrow: true,
      render: (row) => formatHourOfDayMaybe(row.peakHourLocal),
    },
    {
      key: 'population',
      header: 'People',
      numeric: true,
      render: (row) => formatNumberMaybe(row.population, 'people'),
    },
    {
      key: 'phh',
      header: 'Person-heat-hrs',
      numeric: true,
      render: (row) => (
        <span className="font-medium">
          {formatNumberMaybe(row.personHeatHours, 'person_hour')}
        </span>
      ),
    },
  ];

  const panel = (
    <div className="flex flex-col gap-4">
      {/* District statistics */}
      <Card eyebrow="District" title="Statistics" onShowProvenance={() => undefined}>
        {stats === null ? (
          <div className="grid grid-cols-2 gap-3">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : (
          <dl className="grid grid-cols-2 gap-3">
            <StatCell label="Mean" value={stats.Temperature_stats.Mean} meta={meta} />
            <StatCell
              label="Maximum"
              value={stats.Temperature_stats.Maximum}
              meta={meta}
            />
            <StatCell
              label="Minimum"
              value={stats.Temperature_stats.Minimum}
              meta={meta}
            />
            <StatCell
              label="Std deviation"
              value={stats.Temperature_stats.Standard_deviation}
              meta={meta}
            />
          </dl>
        )}
        <p className="mt-3 font-mono text-caption text-ink-muted" data-numeric>
          {formatNumber(tileCount, 'count')} blocks · 80 m
        </p>
      </Card>

      {/* Distribution */}
      <Card eyebrow="Distribution" title="Temperature profile">
        {distributionPoints.length === 0 ? (
          <Skeleton className="h-40" />
        ) : (
          <DistributionChart points={distributionPoints} thresholdC={thresholdC} />
        )}
      </Card>

      {/* Peak hour */}
      <Card eyebrow="Timing" title="When it peaks">
        <PeakHourClock
          peakHourLocal={districtPeakHourLocal}
          hourHistogram={peakHourHistogram}
        />
      </Card>
    </div>
  );

  return (
    <AppShell
      projectId={projectId}
      districtName={districtName}
      districtContext={districtContext}
      breadcrumb={[districtName, 'Diagnose']}
      degradedReason="fixture"
      panel={panel}
    >
      <div className="flex h-full flex-col">
        {/* Layer switcher */}
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-line bg-card px-6 py-3">
          <div className="flex items-center gap-3">
            <SegmentedControl
              label="Analytic layer"
              options={ANALYTIC_OPTIONS}
              value={activeAnalytic}
              onChange={onAnalyticChange}
            />
            <Tooltip
              content={
                activeAnalytic === 'exceedance'
                  ? GLOSSARY.exceedanceHours
                  : activeAnalytic === 'persistence'
                    ? GLOSSARY.persistence
                    : activeAnalytic === 'time_of_measure'
                      ? GLOSSARY.peakHour
                      : meta.explanation
              }
            >
              <span className="cursor-help text-caption text-ink-secondary underline decoration-dotted underline-offset-2">
                What is this?
              </span>
            </Tooltip>
          </div>

          <p className="text-caption text-ink-secondary">{meta.explanation}</p>
        </div>

        {/* Map + ranked table */}
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="relative min-h-0 flex-1">
            {errorMessage !== null ? (
              <div className="p-6">
                <ErrorState
                  message={errorMessage}
                  hint={ERROR_COPY.upstreamUnavailable.hint}
                />
              </div>
            ) : tiles === null || isLoading ? (
              <Skeleton className="size-full rounded-none" />
            ) : (
              <>
                <TileMap
                  tiles={tiles}
                  domain={domain}
                  selectedTileKey={selectedTileKey}
                  onSelectTile={onSelectTile}
                  center={center}
                />
                <div className="pointer-events-none absolute bottom-4 right-4">
                  <MapLegend
                    title={meta.legendTitle}
                    domain={domain}
                    unit={meta.unit}
                    unitLabel={meta.unitLabel}
                  />
                </div>
              </>
            )}
          </div>

          {/* Ranked blocks — the accessible equivalent of the map (SRS §15.7) */}
          <div className="max-h-72 shrink-0 overflow-y-auto border-t border-line p-4">
            <div className="mb-2 flex items-baseline justify-between">
              <h2 className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
                Priority blocks
              </h2>
              <Tooltip content={GLOSSARY.personHeatHours}>
                <span className="cursor-help text-caption text-ink-secondary underline decoration-dotted underline-offset-2">
                  Ranked by person-heat-hours
                </span>
              </Tooltip>
            </div>
            <DataTable
              columns={columns}
              rows={priorities}
              rowKey={(row) => row.tileKey}
              onRowClick={(row) => onSelectTile(row.tileKey)}
              caption="District blocks ranked by exposure-weighted heat dose"
            />
          </div>
        </div>
      </div>
    </AppShell>
  );
}

interface StatCellProps {
  readonly label: string;
  readonly value: number;
  readonly meta: { readonly unit: 'celsius' | 'hour' | 'count' | 'people' | 'person_hour' | 'usd'; readonly unitLabel: string };
}

function StatCell({ label, value, meta }: StatCellProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
        {label}
      </dt>
      {/* The space before the unit is a real text node, not just a margin —
          otherwise copy-paste and screen readers get "4hours". */}
      <dd className="font-mono text-body font-medium text-ink" data-numeric>
        {formatNumber(value, meta.unit)}{' '}
        <span className="text-caption font-normal text-ink-muted">
          {meta.unitLabel}
        </span>
      </dd>
    </div>
  );
}
