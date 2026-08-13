'use client';

import { ErrorState, Skeleton } from '@/components/feedback/States';
import { Card } from '@/components/ui/Card';
import { Icon } from '@/components/ui/Icon';
import { SEMANTIC } from '@/constants';
import { formatNumber } from '@/lib/format';
import type { AgentNodeRecord, GuardVerdict, GuardViolation } from '@/types';

import { useAgentTrace } from './useAgentTrace';

/**
 * Agent Trace / Honesty Panel (SRS screen #10).
 *
 * The page that answers "did a language model make up any of these numbers?"
 *
 * It shows the guard verdict whatever it is. A `retried` or `failed` verdict is
 * displayed as prominently as a pass, with the offending token and its context,
 * because a trace that only ever reported success would be decoration rather than
 * evidence. Catching a fabricated figure is the mechanism working.
 */
export function AgentTracePage({ runId }: { readonly runId: string }) {
  const {
    run,
    isLoading,
    errorMessage,
    verdictSummary,
    llmNodeCount,
    deterministicNodeCount,
    llmTimeShare,
  } = useAgentTrace({ runId });

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5 p-6">
      <header className="flex flex-col gap-1">
        <p className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
          Honesty panel
        </p>
        <h1 className="text-xl font-medium text-ink-primary">
          How this plan’s text was produced
        </h1>
        <p className="text-sm text-ink-secondary">
          Every number in CoolRx comes from the temperature API, the database, the
          model, or plain arithmetic. The language model writes sentences around
          those numbers and is checked, mechanically, for having invented any.
        </p>
      </header>

      {isLoading && <Skeleton className="h-64 w-full" />}
      {errorMessage !== null && (
        <ErrorState
          message={errorMessage}
          hint="The plan itself is unaffected — its figures do not depend on this."
        />
      )}

      {run !== null && (
        <>
          {/* ── Verdict ─────────────────────────────────────────────────── */}
          <Card eyebrow="Numeric guard" title="Verdict">
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <VerdictBadge verdict={run.guardVerdict} />
                <span className="text-sm text-ink-secondary">{verdictSummary}</span>
              </div>

              {run.guardViolations.length > 0 && (
                <ul className="flex flex-col gap-2">
                  {run.guardViolations.map((violation, index) => (
                    <ViolationRow key={`${violation.token}-${index}`} violation={violation} />
                  ))}
                </ul>
              )}

              {run.guardViolations.length === 0 && (
                <p className="text-xs text-ink-secondary">
                  No numeral appeared that had not been supplied as structured input.
                </p>
              )}
            </div>
          </Card>

          {/* ── Nodes ───────────────────────────────────────────────────── */}
          <Card
            eyebrow="Execution"
            title="What ran"
            actions={
              <span className="text-xs text-ink-secondary">
                {deterministicNodeCount} deterministic · {llmNodeCount} language model
              </span>
            }
          >
            <div className="flex flex-col gap-3">
              <ol className="flex flex-col gap-1.5">
                {run.nodes.map((node) => (
                  <NodeRow key={node.name} node={node} />
                ))}
              </ol>

              <p className="text-xs text-ink-secondary">
                The language model ran in {llmNodeCount} of {run.nodes.length} steps,
                accounting for {Math.round(llmTimeShare * 100)}% of the time. It
                receives figures and returns prose; it never computes one.
              </p>
            </div>
          </Card>

          {/* ── Run detail ──────────────────────────────────────────────── */}
          <Card eyebrow="Run" title="Details">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
              <dt className="text-ink-secondary">Model</dt>
              <dd className="text-right font-mono text-ink-primary">{run.model}</dd>

              <dt className="text-ink-secondary">Graph version</dt>
              <dd className="text-right font-mono text-ink-primary">
                {run.graphVersion}
              </dd>

              <dt className="text-ink-secondary">Tokens in / out</dt>
              <dd className="text-right tabular-nums text-ink-primary" data-numeric>
                {run.tokensIn === null ? '—' : formatNumber(run.tokensIn, 'count')}
                {' / '}
                {run.tokensOut === null ? '—' : formatNumber(run.tokensOut, 'count')}
              </dd>

              <dt className="text-ink-secondary">Total time</dt>
              <dd className="text-right tabular-nums text-ink-primary" data-numeric>
                {run.durationMs === null
                  ? '—'
                  : `${(run.durationMs / 1000).toFixed(1)} s`}
              </dd>
            </dl>
          </Card>
        </>
      )}
    </div>
  );
}

const VERDICT_STYLE: Readonly<
  Record<GuardVerdict, { readonly label: string; readonly color: string; readonly bg: string; readonly border: string }>
> = {
  pass: {
    label: 'Passed',
    color: SEMANTIC.verifiedText,
    bg: SEMANTIC.verifiedBg,
    border: SEMANTIC.verifiedBorder,
  },
  retried: {
    label: 'Caught and retried',
    color: SEMANTIC.cautionText,
    bg: SEMANTIC.cautionBg,
    border: SEMANTIC.cautionBorder,
  },
  failed: {
    label: 'Blocked — text discarded',
    color: SEMANTIC.errorText,
    bg: SEMANTIC.errorBg,
    border: SEMANTIC.errorBorder,
  },
};

function VerdictBadge({ verdict }: { readonly verdict: GuardVerdict }) {
  const style = VERDICT_STYLE[verdict];
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded-sharp border px-2 py-0.5 text-xs font-medium"
      style={{
        color: style.color,
        backgroundColor: style.bg,
        borderColor: style.border,
      }}
    >
      <Icon name="guard" size={12} />
      {style.label}
    </span>
  );
}

function ViolationRow({ violation }: { readonly violation: GuardViolation }) {
  return (
    <li className="flex flex-col gap-1 rounded-sharp border border-line bg-subtle px-3 py-2">
      <div className="flex items-baseline gap-2">
        <code className="rounded-[2px] bg-danger-bg px-1 font-mono text-xs text-danger">
          {violation.token}
        </code>
        <span className="text-xs text-ink-secondary">in {violation.node}</span>
      </div>
      {/* The surrounding text, because the token alone does not show whether the
          model invented a figure or reformatted an allowed one. */}
      <p className="text-xs italic text-ink-secondary">“{violation.context}”</p>
      <p className="text-xs text-ink-secondary">{violation.reason}</p>
    </li>
  );
}

function NodeRow({ node }: { readonly node: AgentNodeRecord }) {
  const isLlm = node.type === 'llm';
  return (
    <li className="grid grid-cols-[1.25rem_1fr_auto_auto] items-center gap-2 text-xs">
      <Icon name={isLlm ? 'nodeLlm' : 'nodeDeterministic'} size={14} />
      <span className="truncate font-mono text-ink-primary">{node.name}</span>
      <span className="text-ink-secondary">
        {isLlm ? 'language model' : 'deterministic'}
      </span>
      <span className="w-14 text-right tabular-nums text-ink-secondary" data-numeric>
        {node.durationMs >= 1000
          ? `${(node.durationMs / 1000).toFixed(1)} s`
          : `${node.durationMs} ms`}
      </span>
    </li>
  );
}
