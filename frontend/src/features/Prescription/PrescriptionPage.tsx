'use client';

import { DISCLAIMER, EMPTY_STATE } from '@/constants';
import {
  formatCurrency,
  formatHours,
  formatNumber,
  formatPercentScaled,
} from '@/lib/format';
import type { PlanItem } from '@/types';
import { AppShell } from '@/components/layout/AppShell';
import { EmptyState, ErrorState } from '@/components/feedback/States';
import { Button } from '@/components/ui/Button';
import { type Column, DataTable } from '@/components/ui/DataTable';
import { Estimate } from '@/components/ui/Estimate';
import { Icon } from '@/components/ui/Icon';
import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { StatTile } from '@/components/ui/StatTile';
import { Tag } from '@/components/ui/Tag';
import { BudgetSlider } from '@/components/plan/BudgetSlider';
import { EquityLambdaSlider } from '@/components/plan/EquityLambdaSlider';
import {
  CATEGORY_LEGEND,
  OBJECTIVE_OPTIONS,
  usePrescription,
} from './usePrescription';

interface PrescriptionPageProps {
  readonly projectId: string;
  readonly districtName: string;
  readonly districtContext: string;
}

/**
 * Prescription screen — UI only. All behaviour lives in `usePrescription`.
 *
 * Ported from the Google Stitch "Cooling Prescription Plan" mockup, with three
 * additions the mockup omitted but the SRS requires: the budget-used bar,
 * provenance affordances on every headline figure, and the planning-grade
 * estimate disclaimer.
 */
export function PrescriptionPage({
  projectId,
  districtName,
  districtContext,
}: PrescriptionPageProps) {
  const {
    plan,
    isOptimizing,
    errorMessage,
    budgetUsd,
    objective,
    equityLambda,
    budgetUsedFraction,
    onBudgetChange,
    onObjectiveChange,
    onEquityLambdaChange,
    onOptimize,
  } = usePrescription({ projectId, planId: null });

  const columns: readonly Column<PlanItem>[] = [
    {
      key: 'rank',
      header: 'Rank',
      numeric: true,
      width: '4rem',
      render: (row) => String(row.rank).padStart(2, '0'),
    },
    {
      key: 'block',
      header: 'Block',
      width: '6rem',
      render: (row) => <span className="font-mono">{row.tileKey}</span>,
    },
    {
      key: 'intervention',
      header: 'Intervention',
      render: (row) => <Tag category={row.category}>{row.interventionName}</Tag>,
    },
    {
      key: 'quantity',
      header: 'Quantity',
      numeric: true,
      render: (row) => `${formatNumber(row.quantity, 'count')} ${row.unit}`,
    },
    {
      key: 'unitCost',
      header: 'Unit cost',
      numeric: true,
      render: (row) => formatCurrency(row.unitCostUsd),
    },
    {
      key: 'totalCost',
      header: 'Total cost',
      numeric: true,
      render: (row) => (
        <span className="font-medium">{formatCurrency(row.costUsd)}</span>
      ),
    },
    {
      key: 'delta',
      header: 'Predicted ΔT',
      render: (row) => (
        <Estimate estimate={row.predictedDelta} size="inline" showMarker={false} />
      ),
    },
    {
      key: 'heatHours',
      header: 'Heat-hrs',
      numeric: true,
      hideOnNarrow: true,
      render: (row) => formatNumber(row.heatHoursAvoided, 'hour'),
    },
    {
      key: 'people',
      header: 'People',
      numeric: true,
      hideOnNarrow: true,
      render: (row) => formatNumber(row.peopleAffected, 'people'),
    },
  ];

  return (
    <AppShell
      projectId={projectId}
      districtName={districtName}
      districtContext={districtContext}
      breadcrumb={[districtName, 'Prescribe']}
      degradedReason="fixture"
      scrollMain
    >
      <div className="flex flex-col gap-6">
        {/* ── Title ─────────────────────────────────────────────────────── */}
        <header>
          <h1 className="text-title font-semibold text-accent-strong">
            Intervention prescription
          </h1>
          <p className="mt-1 text-body text-ink-secondary">
            Configure constraints to generate an optimised cooling portfolio.
          </p>
        </header>

        {/* ── Control strip ─────────────────────────────────────────────── */}
        <section className="grid grid-cols-1 items-end gap-6 rounded-sharp border border-line bg-card p-5 lg:grid-cols-[1fr_auto_1fr_auto]">
          <BudgetSlider value={budgetUsd} onChange={onBudgetChange} />

          <div className="flex flex-col gap-2">
            <span className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
              Objective function
            </span>
            <SegmentedControl
              label="Optimisation objective"
              options={OBJECTIVE_OPTIONS}
              value={objective}
              onChange={onObjectiveChange}
            />
          </div>

          <EquityLambdaSlider value={equityLambda} onChange={onEquityLambdaChange} />

          <Button
            variant="primary"
            icon="optimize"
            onClick={onOptimize}
            disabled={isOptimizing}
          >
            {isOptimizing ? 'Optimising…' : 'Optimize plan'}
          </Button>
        </section>

        {errorMessage !== null ? (
          <ErrorState
            message={errorMessage}
            hint="Cached districts remain available."
            onRetry={onOptimize}
          />
        ) : null}

        {plan === null ? (
          <EmptyState
            message={EMPTY_STATE.noPlan.message}
            hint={EMPTY_STATE.noPlan.hint}
            actionLabel={EMPTY_STATE.noPlan.action}
            onAction={onOptimize}
          />
        ) : (
          <>
            {/* ── Headline impact ───────────────────────────────────────── */}
            <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
              <StatTile
                label="Mean cooling"
                icon="temperature"
                onShowProvenance={() => undefined}
              >
                {/* Marker shown here: the label "Mean cooling" does not itself
                    say the value is predicted. In the table below it is
                    suppressed because the column header reads "Predicted ΔT". */}
                <Estimate estimate={plan.totals.meanDelta} size="hero" />
              </StatTile>

              <StatTile
                label="Heat-hours avoided"
                icon="exceedance"
                onShowProvenance={() => undefined}
              >
                {formatHours(plan.totals.heatHoursAvoided)}
              </StatTile>

              <StatTile
                label="Person-heat-hours"
                icon="population"
                detail="People multiplied by dangerous hours avoided"
                onShowProvenance={() => undefined}
              >
                {formatNumber(plan.totals.personHeatHoursAvoided, 'person_hour')}
              </StatTile>

              <StatTile
                label="People reached"
                icon="vulnerability"
                detail={
                  plan.totals.pctReachedTopSviQuartile === null
                    ? 'Vulnerability breakdown unavailable for this area'
                    : `${formatPercentScaled(plan.totals.pctReachedTopSviQuartile)} in the most vulnerable quartile`
                }
                onShowProvenance={() => undefined}
              >
                {formatNumber(plan.totals.peopleReached, 'people')}
              </StatTile>
            </section>

            {/* ── Estimate disclaimer — required beside predicted figures ── */}
            <p className="flex items-start gap-2 rounded-sharp border border-caution-line bg-caution-bg px-4 py-2.5 text-caption text-caution">
              <Icon name="caution" size={14} className="mt-0.5" />
              {DISCLAIMER.estimate}
            </p>

            {/* ── Category legend ───────────────────────────────────────── */}
            <div className="flex flex-wrap items-center gap-4">
              <span className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
                Interventions
              </span>
              {CATEGORY_LEGEND.map((entry) => (
                <span
                  key={entry.category}
                  className="flex items-center gap-1.5 text-caption text-ink-secondary"
                >
                  <span
                    aria-hidden
                    className="size-3 rounded-[2px]"
                    style={{ backgroundColor: entry.color }}
                  />
                  {entry.label}
                </span>
              ))}
            </div>

            {/* ── Plan table ────────────────────────────────────────────── */}
            <DataTable
              columns={columns}
              rows={plan.items}
              rowKey={(row) => row.id}
              caption="Recommended cooling interventions, ranked by cooling per dollar"
              footer={
                <div className="flex flex-col gap-2">
                  <div className="flex items-baseline justify-between gap-4">
                    <span className="text-caption text-ink-secondary">
                      Budget used
                    </span>
                    <span
                      className="font-mono text-caption font-medium text-ink"
                      data-numeric
                    >
                      {formatCurrency(plan.totals.totalCostUsd)} of{' '}
                      {formatCurrency(plan.budgetUsd)}
                    </span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-[2px] bg-inset">
                    <div
                      className="h-full bg-accent"
                      style={{ width: `${budgetUsedFraction * 100}%` }}
                    />
                  </div>
                </div>
              }
            />
          </>
        )}
      </div>
    </AppShell>
  );
}
