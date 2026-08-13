'use client';

import { ErrorState, Skeleton } from '@/components/feedback/States';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Estimate } from '@/components/ui/Estimate';
import { Icon } from '@/components/ui/Icon';
import { SEMANTIC } from '@/constants';
import { formatNumber } from '@/lib/format';
import type { VerificationProtocol } from '@/types';

import { useVerification, type DifferenceBreakdown } from './useVerification';

/**
 * Verify (SRS screen #9).
 *
 * The screen where careless wording would do the most damage, so the language is
 * constrained throughout. The verdict is **"within the predicted range"**, never
 * "the plan worked": a prediction can be right about a disappointing outcome, and
 * an observation outside the range says something about the model rather than
 * about the intervention.
 *
 * The difference-in-differences arithmetic is shown decomposed rather than as a
 * single figure. Showing only the result asks the reader to trust that controls
 * were subtracted; showing both changes lets them check, and makes the weather
 * component impossible to miss.
 */
export function VerificationPage({ planId }: { readonly planId: string }) {
  const {
    protocol,
    result,
    breakdown,
    weatherComponentC,
    isLoading,
    isRunning,
    errorMessage,
    followupDate,
    onFollowupDateChange,
    onRunVerification,
  } = useVerification({ planId });

  if (isLoading) {
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-4 p-6">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (protocol === null) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <ErrorState
          message="No measurement protocol exists for this plan."
          hint="A protocol is issued when a plan is generated."
        />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5 p-6">
      <header className="flex flex-col gap-1">
        <p className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
          Verification
        </p>
        <h1 className="text-xl font-medium text-ink-primary">
          Did the measured temperature move as predicted?
        </h1>
      </header>

      {/* ── Protocol ────────────────────────────────────────────────────── */}
      <Card eyebrow="Protocol" title="Committed in advance">
        <div className="flex flex-col gap-3">
          {/* The credibility argument, stated where it applies. */}
          <p className="text-sm text-ink-secondary">
            The treated and control blocks below were named when the plan was
            generated, before any measurement was taken. That is what stops them
            being chosen afterwards to favour the result.
          </p>
          <ProtocolDetails protocol={protocol} />
        </div>
      </Card>

      {/* ── Run ─────────────────────────────────────────────────────────── */}
      <Card eyebrow="Re-measure" title="Take the follow-up measurement">
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1">
              <label htmlFor="followup-date" className="text-xs text-ink-secondary">
                Follow-up date
              </label>
              <input
                id="followup-date"
                type="date"
                value={followupDate}
                onChange={(event) => onFollowupDateChange(event.target.value)}
                className="rounded-sharp border border-line bg-card px-2 py-1.5 font-mono text-sm text-ink-primary"
              />
            </div>
            <Button
              variant="primary"
              icon="measure"
              onClick={onRunVerification}
              disabled={isRunning || followupDate === ''}
            >
              {isRunning ? 'Measuring…' : 'Re-measure'}
            </Button>
          </div>
          <p className="text-xs text-ink-secondary">
            Measured at {protocol.startTime} UTC at {protocol.granularity} m, matching
            the baseline exactly. A different hour or resolution would make the two
            measurements incomparable.
          </p>
        </div>
      </Card>

      {errorMessage !== null && (
        <ErrorState message={errorMessage} hint="Nothing was changed." />
      )}

      {/* ── Result ──────────────────────────────────────────────────────── */}
      {result !== null && breakdown !== null && (
        <>
          <Card eyebrow="Result" title="Observed against predicted">
            <div className="flex flex-col gap-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-1">
                  <span className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
                    Observed change
                  </span>
                  <span className="font-mono text-2xl text-ink-primary" data-numeric>
                    {formatNumber(result.observedDeltaC, 'celsius')} °C
                  </span>
                  <span className="text-xs text-ink-secondary">
                    after subtracting the control blocks
                  </span>
                </div>

                <div className="flex flex-col gap-1">
                  <span className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
                    Predicted
                  </span>
                  <Estimate estimate={result.predictedDelta} size="hero" />
                </div>
              </div>

              <VerdictBanner withinCi={result.withinCi} />
            </div>
          </Card>

          {/* ── The arithmetic ─────────────────────────────────────────── */}
          <Card eyebrow="Method" title="How the observed change was calculated">
            <div className="flex flex-col gap-3">
              <dl className="flex flex-col gap-1.5 text-sm">
                <ChangeRow
                  label="Treated blocks"
                  before={result.treatedBaselineC}
                  after={result.treatedFollowupC}
                  change={breakdown.treatedChange}
                />
                <ChangeRow
                  label="Control blocks"
                  before={result.controlBaselineC}
                  after={result.controlFollowupC}
                  change={breakdown.controlChange}
                />
                <div className="mt-1 flex items-baseline justify-between border-t border-line pt-2">
                  <dt className="text-sm font-medium text-ink-primary">
                    Difference of differences
                  </dt>
                  <dd className="font-mono text-sm font-medium text-ink-primary" data-numeric>
                    {formatNumber(breakdown.difference, 'celsius')} °C
                  </dd>
                </div>
              </dl>

              {/* The number that justifies the whole design. */}
              {weatherComponentC !== null && Math.abs(weatherComponentC) > 0.05 && (
                <p className="rounded-sharp border border-line bg-subtle p-3 text-xs text-ink-secondary">
                  The control blocks{' '}
                  {weatherComponentC > 0 ? 'warmed' : 'cooled'} by{' '}
                  {formatNumber(Math.abs(weatherComponentC), 'celsius')} °C between the
                  two dates without any intervention. Subtracting that is why the
                  reported change is{' '}
                  {formatNumber(breakdown.difference, 'celsius')} °C rather than{' '}
                  {formatNumber(breakdown.treatedChange, 'celsius')} °C — the
                  difference would otherwise have been credited to the plan.
                </p>
              )}

              <p className="text-xs text-ink-secondary">{result.caveat}</p>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

/**
 * The verdict.
 *
 * Says "within the predicted range", not "the plan worked". An observation
 * outside the range is information about the model's calibration, not a verdict
 * on the intervention — and either way this is a comparison of two measurements,
 * not a causal finding.
 */
function VerdictBanner({ withinCi }: { readonly withinCi: boolean }) {
  return (
    <p
      className="flex items-start gap-2 rounded-sharp border px-3 py-2 text-sm"
      style={{
        color: withinCi ? SEMANTIC.verifiedText : SEMANTIC.cautionText,
        backgroundColor: withinCi ? SEMANTIC.verifiedBg : SEMANTIC.cautionBg,
        borderColor: withinCi ? SEMANTIC.verifiedBorder : SEMANTIC.cautionBorder,
      }}
    >
      <Icon name={withinCi ? 'verified' : 'caution'} size={15} />
      <span>
        {withinCi
          ? 'The observed change fell within the predicted range. The model’s '
            + 'estimate for this plan is consistent with what was measured.'
          : 'The observed change fell outside the predicted range. That is a '
            + 'finding about the model’s calibration on this district, and it is '
            + 'recorded rather than adjusted away.'}
      </span>
    </p>
  );
}

function ChangeRow({
  label,
  before,
  after,
  change,
}: {
  readonly label: string;
  readonly before: number;
  readonly after: number;
  readonly change: number;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-ink-secondary">{label}</dt>
      <dd className="flex items-baseline gap-2 font-mono text-xs" data-numeric>
        <span className="text-ink-secondary">
          {formatNumber(before, 'celsius')} → {formatNumber(after, 'celsius')} °C
        </span>
        <span className="w-16 text-right text-ink-primary">
          {change > 0 ? '+' : ''}
          {formatNumber(change, 'celsius')} °C
        </span>
      </dd>
    </div>
  );
}

function ProtocolDetails({
  protocol,
}: {
  readonly protocol: VerificationProtocol;
}) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
      <dt className="text-ink-secondary">Treated blocks</dt>
      <dd className="text-right tabular-nums text-ink-primary" data-numeric>
        {protocol.treatedTileKeys.length}
      </dd>

      <dt className="text-ink-secondary">Control blocks</dt>
      <dd className="text-right tabular-nums text-ink-primary" data-numeric>
        {protocol.controlTileKeys.length}
      </dd>

      <dt className="text-ink-secondary">Scheduled for</dt>
      <dd className="text-right font-mono text-ink-primary">
        {protocol.scheduledFor}
      </dd>

      <dt className="text-ink-secondary">Test</dt>
      <dd className="text-right text-ink-primary">difference-in-differences</dd>
    </dl>
  );
}
