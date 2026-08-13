'use client';

import Link from 'next/link';

import { ErrorState, Skeleton } from '@/components/feedback/States';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { type Column, DataTable } from '@/components/ui/DataTable';
import { Estimate } from '@/components/ui/Estimate';
import { Icon } from '@/components/ui/Icon';
import { DISCLAIMER, INTERVENTION_COLORS } from '@/constants';
import {
  formatCurrency,
  formatNumber,
  formatNumberMaybe,
} from '@/lib/format';
import type { PlanItem, ProvenanceRecord } from '@/types';

import { useActionPlan, type CategoryRollup } from './useActionPlan';

/**
 * Cooling Action Plan (SRS screen #8).
 *
 * The deliverable. Everything above is analysis; this is the document a city
 * department actually receives, so it carries the whole evidence chain: what to
 * build, what it costs, what it is predicted to achieve with what uncertainty,
 * how it will be measured afterwards, and where every number came from.
 *
 * It prints. The print stylesheet renders this same DOM rather than a separate
 * server-side template, because a second rendering path is a second thing that
 * can disagree with the first — and the report's entire claim is that every
 * figure traces to one source.
 */
export function ActionPlanPage({ planId }: { readonly planId: string }) {
  const {
    plan,
    items,
    provenance,
    rollup,
    itemsWithoutRationale,
    isLoading,
    errorMessage,
    isPrinting,
    onDownload,
  } = useActionPlan({ planId });

  if (isLoading) {
    return (
      <div className="mx-auto flex max-w-4xl flex-col gap-4 p-6">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (errorMessage !== null || plan === null) {
    return (
      <div className="mx-auto max-w-4xl p-6">
        <ErrorState
          message={errorMessage ?? 'This plan could not be found.'}
          hint="Generate a plan from the Prescription page."
        />
      </div>
    );
  }

  const columns: readonly Column<PlanItem>[] = [
    {
      key: 'rank',
      header: '#',
      numeric: true,
      width: '2.5rem',
      render: (row) => String(row.rank).padStart(2, '0'),
    },
    {
      key: 'block',
      header: 'Block',
      width: '5.5rem',
      render: (row) => <span className="font-mono text-xs">{row.tileKey}</span>,
    },
    {
      key: 'intervention',
      header: 'Intervention',
      render: (row) => (
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="size-2 shrink-0 rounded-[2px]"
            style={{ backgroundColor: INTERVENTION_COLORS[row.category] }}
          />
          {row.interventionName}
        </span>
      ),
    },
    {
      key: 'quantity',
      header: 'Qty',
      numeric: true,
      render: (row) => `${formatNumber(row.quantity, 'count')} ${row.unit}`,
    },
    {
      key: 'cost',
      header: 'Cost',
      numeric: true,
      render: (row) => formatCurrency(row.costUsd),
    },
    {
      key: 'delta',
      header: 'Predicted ΔT',
      numeric: true,
      render: (row) => (
        <Estimate estimate={row.predictedDelta} size="inline" showMarker={false} />
      ),
    },
    {
      key: 'hours',
      header: 'Hours avoided',
      numeric: true,
      hideOnNarrow: true,
      render: (row) => formatNumberMaybe(row.heatHoursAvoided, 'hour'),
    },
  ];

  return (
    <article className="mx-auto flex max-w-4xl flex-col gap-5 p-6 print:max-w-none print:p-0">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <p className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
            Cooling Action Plan
          </p>
          <h1 className="text-xl font-medium text-ink-primary">
            {items.length} interventions across {new Set(items.map((i) => i.tileKey)).size}{' '}
            blocks
          </h1>
          <p className="font-mono text-xs text-ink-secondary">
            Plan {plan.id} · model {plan.modelVersion} ·{' '}
            {new Date(plan.createdAt).toISOString().slice(0, 10)}
          </p>
        </div>

        <div className="flex gap-2 print:hidden">
          <Button variant="secondary" icon="download" onClick={onDownload}>
            {isPrinting ? 'Preparing…' : 'Download PDF'}
          </Button>
        </div>
      </header>

      {/* ── The claim, with its caveat attached ─────────────────────────── */}
      <Card eyebrow="Predicted impact" title="What this plan is expected to achieve">
        <div className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <Headline label="Mean cooling across the district">
              <Estimate estimate={plan.totals.meanDelta} size="hero" />
            </Headline>
            <Headline label="Dangerous hours avoided">
              <span className="font-mono text-xl text-ink-primary" data-numeric>
                {formatNumber(plan.totals.heatHoursAvoided, 'hour')}
              </span>
            </Headline>
            <Headline label="People reached">
              <span className="font-mono text-xl text-ink-primary" data-numeric>
                {formatNumber(plan.totals.peopleReached, 'people')}
              </span>
            </Headline>
          </div>

          {/* Required beside the figures, not in a footnote (P4). */}
          <p className="rounded-sharp border border-line bg-subtle p-3 text-xs text-ink-secondary">
            {plan.estimateDisclaimer}
          </p>
        </div>
      </Card>

      {/* ── Budget ──────────────────────────────────────────────────────── */}
      <Card eyebrow="Cost" title="Where the money goes">
        <div className="flex flex-col gap-3">
          <div className="flex items-baseline justify-between text-sm">
            <span className="text-ink-secondary">Total committed</span>
            <span className="font-mono font-medium text-ink-primary" data-numeric>
              {formatCurrency(plan.totals.totalCostUsd)} of{' '}
              {formatCurrency(plan.totals.budgetUsd)}
            </span>
          </div>

          <ul className="flex flex-col gap-1.5">
            {rollup.map((row) => (
              <RollupRow key={row.category} row={row} />
            ))}
          </ul>
        </div>
      </Card>

      {/* ── The plan ────────────────────────────────────────────────────── */}
      <Card eyebrow="Schedule" title="Interventions, in priority order">
        <DataTable<PlanItem>
          rows={items}
          columns={columns}
          rowKey={(row) => row.id}
          caption="Selected interventions ranked by cost-effectiveness"
        />
      </Card>

      {/* ── Rationales ──────────────────────────────────────────────────── */}
      <Card eyebrow="Reasoning" title="Why these blocks">
        <div className="flex flex-col gap-3">
          <ul className="flex flex-col gap-2.5">
            {items
              .filter((item) => item.rationale !== null)
              .slice(0, 5)
              .map((item) => (
                <li key={item.id} className="flex flex-col gap-0.5 text-sm">
                  <span className="font-mono text-xs text-ink-secondary">
                    {item.tileKey} · {item.interventionName}
                  </span>
                  <span className="text-ink-secondary">{item.rationale}</span>
                </li>
              ))}
          </ul>

          {/* Shown rather than hidden: a dropped rationale means the guard caught
              the model inventing a figure, which is the system working. */}
          {itemsWithoutRationale > 0 && (
            <p className="flex items-start gap-2 rounded-sharp border border-line bg-subtle p-3 text-xs text-ink-secondary">
              <Icon name="guard" size={14} />
              <span>
                {itemsWithoutRationale}{' '}
                {itemsWithoutRationale === 1 ? 'item has' : 'items have'} no written
                rationale. The numeric guard rejected the generated text for those,
                so it was discarded rather than shown. The figures are unaffected —
                they never come from the language model.{' '}
                <Link href="/methods" className="underline print:no-underline">
                  How this works
                </Link>
              </span>
            </p>
          )}
        </div>
      </Card>

      {/* ── Measurement ─────────────────────────────────────────────────── */}
      <Card eyebrow="Verification" title="How to check whether it worked">
        <div className="flex flex-col gap-3 text-sm text-ink-secondary">
          <p>
            Re-measure the same blocks one season after installation, at the same
            hour, at the same resolution. Compare the change against untreated
            control blocks matched on baseline temperature and land cover.
          </p>
          <p>{DISCLAIMER.verification}</p>
          <Link
            href={`/plans/${plan.id}/verify`}
            className="text-sm text-accent underline print:hidden"
          >
            Open the measurement protocol
          </Link>
        </div>
      </Card>

      {/* ── Provenance ──────────────────────────────────────────────────── */}
      <Card
        eyebrow="Provenance"
        title="Where every figure came from"
        actions={
          <span className="text-xs text-ink-secondary">{provenance.length} figures</span>
        }
      >
        <ul className="flex flex-col divide-y divide-line">
          {provenance.map((record) => (
            <ProvenanceRow key={record.figureLabel} record={record} />
          ))}
        </ul>
      </Card>

      {/* ── Scope ───────────────────────────────────────────────────────── */}
      <Card eyebrow="Scope" title="Before commissioning any of this">
        <p className="text-sm text-ink-secondary">{DISCLAIMER.humanReview}</p>
      </Card>
    </article>
  );
}

function Headline({
  label,
  children,
}: {
  readonly label: string;
  readonly children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
        {label}
      </span>
      {children}
    </div>
  );
}

const CATEGORY_LABEL: Readonly<Record<string, string>> = {
  green: 'Trees and planting',
  water: 'Water and misting',
  shade: 'Built shade',
  material: 'Surfaces and roofs',
};

function RollupRow({ row }: { readonly row: CategoryRollup }) {
  return (
    <li className="grid grid-cols-[1fr_auto_5rem] items-center gap-3 text-xs">
      <span className="flex items-center gap-1.5 truncate">
        <span
          aria-hidden="true"
          className="size-2 shrink-0 rounded-[2px]"
          style={{ backgroundColor: INTERVENTION_COLORS[row.category] }}
        />
        <span className="text-ink-secondary">
          {CATEGORY_LABEL[row.category] ?? row.category}
        </span>
        <span className="text-ink-muted">
          ({row.itemCount} {row.itemCount === 1 ? 'site' : 'sites'})
        </span>
      </span>

      {/* Proportional bar. Redundant with the number beside it on purpose —
          the bar is for scanning, the number is for citing. */}
      <span className="hidden h-1.5 w-24 overflow-hidden rounded-full bg-subtle sm:block">
        <span
          className="block h-full"
          style={{
            width: `${row.shareOfBudget * 100}%`,
            backgroundColor: INTERVENTION_COLORS[row.category],
          }}
        />
      </span>

      <span className="text-right font-mono text-ink-primary" data-numeric>
        {formatCurrency(row.costUsd)}
      </span>
    </li>
  );
}

const SOURCE_LABEL: Readonly<Record<string, string>> = {
  fortyguard: 'Measured',
  derived: 'Derived',
  model: 'Model',
  catalog: 'Catalog',
  external_dataset: 'External data',
};

function ProvenanceRow({ record }: { readonly record: ProvenanceRecord }) {
  return (
    <li className="flex flex-col gap-1 py-2.5 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm text-ink-primary">{record.figureLabel}</span>
        <span className="font-mono text-sm text-ink-primary" data-numeric>
          {record.value}
        </span>
      </div>
      <div className="flex flex-wrap items-baseline gap-2 text-xs text-ink-secondary">
        <span className="rounded-[2px] border border-line bg-subtle px-1.5 py-0.5">
          {SOURCE_LABEL[record.sourceType] ?? record.sourceType}
        </span>
        <span>{record.sourceDetail}</span>
      </div>
      {/* The FortyGuard handle is the anchor that makes a figure re-checkable
          against the source months later. */}
      {record.activityId !== null && (
        <span className="font-mono text-xs text-ink-muted">
          activity {record.activityId}
        </span>
      )}
    </li>
  );
}
