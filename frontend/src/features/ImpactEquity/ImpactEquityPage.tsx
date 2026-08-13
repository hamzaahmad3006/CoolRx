'use client';

import { AppShell } from '@/components/layout/AppShell';
import { EquityLambdaSlider } from '@/components/plan/EquityLambdaSlider';
import { Card } from '@/components/ui/Card';
import { Icon } from '@/components/ui/Icon';
import { Tooltip } from '@/components/ui/Tooltip';
import { DISCLAIMER, GLOSSARY, HEAT_SCALE, SEMANTIC } from '@/constants';
import { formatNumber } from '@/lib/format';
import type { EquityDecile, VulnerableGroupBreakdown } from '@/types';

import { MOST_VULNERABLE_DECILES, useImpactEquity } from './useImpactEquity';

/**
 * Impact & Equity (SRS screen #7).
 *
 * Answers "who benefits" rather than "how much cooling". The headline is a
 * comparison, not a single number: what share of the benefit reaches the most
 * vulnerable deciles, set against what share of the population they are. A bare
 * "42% of benefit reaches vulnerable areas" sounds impressive and means nothing
 * until you know whether they are 42% of the district.
 */
export function ImpactEquityPage({ projectId }: { readonly projectId: string }) {
  const {
    deciles,
    groups,
    equityLambda,
    shareToMostVulnerable,
    populationShareMostVulnerable,
    isProgressive,
    untreatedDeciles,
    onLambdaChange,
  } = useImpactEquity();

  const panel = (
    <div className="flex flex-col gap-4">
      <Card eyebrow="Weighting" title="Equity weight">
        <div className="flex flex-col gap-3">
          <EquityLambdaSlider value={equityLambda} onChange={onLambdaChange} />
          <p className="text-xs text-ink-secondary">{DISCLAIMER.equityLambda}</p>
        </div>
      </Card>

      <Card eyebrow="Groups" title="Who is reached">
        <ul className="flex flex-col gap-3">
          {groups.map((group) => (
            <GroupRow key={group.group} group={group} />
          ))}
        </ul>
      </Card>

      <Card eyebrow="Caveat" title="Resolution">
        <p className="text-xs text-ink-secondary">{DISCLAIMER.vulnerability}</p>
      </Card>
    </div>
  );

  return (
    <AppShell
      projectId={projectId}
      districtName="Impact and equity"
      districtContext="Who benefits from this plan"
      breadcrumb={['Impact & Equity']}
      panel={panel}
    >
      <div className="flex flex-col gap-5 overflow-y-auto p-5">
        {/* ── The comparison that matters ─────────────────────────────── */}
        <Card
          eyebrow="Headline"
          title="Does the benefit reach the people who need it?"
        >
          <div className="flex flex-col gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Comparison
                label="Share of benefit to the most vulnerable"
                value={shareToMostVulnerable}
                emphasis
              />
              <Comparison
                label="Their share of district population"
                value={populationShareMostVulnerable}
              />
            </div>

            <p
              className="rounded-sharp border px-3 py-2 text-sm"
              style={{
                color: isProgressive
                  ? SEMANTIC.verifiedText
                  : SEMANTIC.cautionText,
                backgroundColor: isProgressive
                  ? SEMANTIC.verifiedBg
                  : SEMANTIC.cautionBg,
                borderColor: isProgressive
                  ? SEMANTIC.verifiedBorder
                  : SEMANTIC.cautionBorder,
              }}
            >
              {isProgressive
                ? `Deciles ${MOST_VULNERABLE_DECILES.join(', ')} receive a larger share of the cooling benefit than their share of the population. The plan is weighted towards them.`
                : `Deciles ${MOST_VULNERABLE_DECILES.join(', ')} receive no more benefit than their population share. Raising the equity weight would shift the plan towards them, at some cost in total hours avoided.`}
            </p>

            <p className="text-xs text-ink-secondary">
              “Most vulnerable” means deciles{' '}
              {MOST_VULNERABLE_DECILES.join(', ')} of the Social Vulnerability
              Index — a line drawn on a continuous scale, stated here so this
              figure can be compared with another district’s.
            </p>
          </div>
        </Card>

        {/* ── Distribution ────────────────────────────────────────────── */}
        <Card
          eyebrow="Distribution"
          title="Benefit by vulnerability decile"
          actions={
            <Tooltip content={GLOSSARY.personHeatHours}>
              <span className="cursor-help text-caption text-ink-secondary underline decoration-dotted underline-offset-2">
                person-heat-hours avoided
              </span>
            </Tooltip>
          }
        >
          <div className="flex flex-col gap-3">
            <ol className="flex flex-col gap-1">
              {deciles.map((decile) => (
                <DecileRow
                  key={decile.decile}
                  decile={decile}
                  peak={Math.max(
                    ...deciles.map((d) => d.personHeatHoursAvoided),
                    1,
                  )}
                />
              ))}
            </ol>

            <p className="text-xs text-ink-secondary">
              Decile 1 is least vulnerable, 10 most. Bars show dangerous exposure
              removed, not degrees of cooling — a small temperature change in a
              crowded block outweighs a large one where nobody lives.
            </p>

            {/* A zero is a planning fact, not a rendering artefact. */}
            {untreatedDeciles.length > 0 && (
              <p className="flex items-start gap-2 rounded-sharp border border-line bg-subtle p-3 text-xs text-ink-secondary">
                <Icon name="caution" size={14} />
                <span>
                  {untreatedDeciles.length === 1 ? 'Decile' : 'Deciles'}{' '}
                  {untreatedDeciles.join(', ')} receive no benefit from this plan.
                  No block there was cost-effective enough to be selected within the
                  budget.
                </span>
              </p>
            )}
          </div>
        </Card>
      </div>
    </AppShell>
  );
}

function Comparison({
  label,
  value,
  emphasis = false,
}: {
  readonly label: string;
  readonly value: number;
  readonly emphasis?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
        {label}
      </span>
      <span
        className={
          emphasis
            ? 'font-mono text-2xl font-medium text-ink-primary'
            : 'font-mono text-2xl text-ink-secondary'
        }
        data-numeric
      >
        {(value * 100).toFixed(0)}%
      </span>
    </div>
  );
}

function DecileRow({
  decile,
  peak,
}: {
  readonly decile: EquityDecile;
  readonly peak: number;
}) {
  const width = (decile.personHeatHoursAvoided / peak) * 100;
  // Ramped by vulnerability so the visual weight matches the axis meaning.
  const color =
    HEAT_SCALE[
      Math.min(HEAT_SCALE.length - 1, Math.floor((decile.decile - 1) / 1.6))
    ] ?? HEAT_SCALE[0];

  return (
    <li className="grid grid-cols-[2rem_1fr_5rem] items-center gap-2 text-xs">
      <span className="text-right font-mono text-ink-secondary" data-numeric>
        {decile.decile}
      </span>

      <span className="h-3 overflow-hidden rounded-[2px] bg-subtle" aria-hidden="true">
        {width > 0 && (
          <span
            className="block h-full rounded-[2px]"
            style={{ width: `${width}%`, backgroundColor: color }}
          />
        )}
      </span>

      <span className="text-right font-mono tabular-nums text-ink-primary" data-numeric>
        {decile.personHeatHoursAvoided > 0
          ? formatNumber(decile.personHeatHoursAvoided, 'person_hour')
          : 'none'}
      </span>
    </li>
  );
}

function GroupRow({ group }: { readonly group: VulnerableGroupBreakdown }) {
  return (
    <li className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs text-ink-secondary">{group.group}</span>
        <span className="font-mono text-xs text-ink-primary" data-numeric>
          {formatNumber(group.populationReached, 'people')}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-subtle">
          <span
            className="block h-full bg-accent"
            style={{ width: `${group.shareOfGroupReached * 100}%` }}
          />
        </span>
        <span className="w-9 text-right font-mono text-[0.65rem] text-ink-secondary" data-numeric>
          {(group.shareOfGroupReached * 100).toFixed(0)}%
        </span>
      </div>
    </li>
  );
}
