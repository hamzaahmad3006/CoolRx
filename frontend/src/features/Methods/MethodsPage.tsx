'use client';

import { Card } from '@/components/ui/Card';
import { Icon } from '@/components/ui/Icon';
import { DISCLAIMER } from '@/constants';
import { formatNumber } from '@/lib/format';

import { useMethods } from './useMethods';

/**
 * Methods and limitations (SRS screen #10, second route).
 *
 * The page a sceptical reader is sent to. It states what the model is, how it was
 * validated, and — at equal prominence — what it cannot do.
 *
 * Interval coverage is given its own callout because it is the number that decides
 * whether every other interval on the site can be believed. A model reporting
 * p10–p90 bounds that only contain 60% of held-out observations is producing
 * intervals that are too narrow, and every figure in every plan would be
 * overconfident by the same margin.
 */
export function MethodsPage() {
  const { validation, coverageIsHealthy, coverageState, coverageTarget } =
    useMethods();

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5 p-6">
      <header className="flex flex-col gap-1">
        <p className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
          Methods
        </p>
        <h1 className="text-xl font-medium text-ink-primary">
          How CoolRx produces its numbers
        </h1>
      </header>

      {/* ── The chain ───────────────────────────────────────────────────── */}
      <Card eyebrow="Pipeline" title="Where each figure comes from">
        <ol className="flex flex-col gap-3 text-sm">
          <Step
            n={1}
            title="Measured temperature"
            body="The FortyGuard Temperature API returns air temperature at head height for every block in the area, plus hours above a danger threshold, longest unbroken stretch, and peak hour. These are measurements, not our estimates."
          />
          <Step
            n={2}
            title="Why a block is hot"
            body="A gradient-boosted model trained on those measurements attributes each block's temperature anomaly to its land cover and terrain. It reports which features drive the prediction — statistical association, not proven physical cause."
          />
          <Step
            n={3}
            title="What an intervention would do"
            body="Each intervention carries a published cooling range with a citation. Predicted cooling is clamped to that range, so a physically absurd figure cannot be displayed regardless of what the model returns."
          />
          <Step
            n={4}
            title="Degrees into hours of danger"
            body="The exceedance ladder measures hours-above-threshold at eleven thresholds. Predicted cooling is read off that curve, converting a temperature change into hours of dangerous heat avoided using the API's own analytic rather than a model of ours."
          />
          <Step
            n={5}
            title="Hours into people"
            body="Hours avoided are multiplied by the block's population to give person-heat-hours, then optionally weighted by social vulnerability. The weighting strength is a policy choice you set, not a constant we picked."
          />
        </ol>
      </Card>

      {/* ── Assumptions ─────────────────────────────────────────────────── */}
      <Card eyebrow="Assumptions" title="What we assume, stated plainly">
        <div className="flex flex-col gap-3 text-sm text-ink-secondary">
          <p>{DISCLAIMER.impactConversion}</p>
          <p>{DISCLAIMER.estimate}</p>
          <p>{DISCLAIMER.population}</p>
          <p>{DISCLAIMER.vulnerability}</p>
        </div>
      </Card>

      {/* ── Scope ───────────────────────────────────────────────────────── */}
      <Card eyebrow="Scope" title="What this tool is for">
        <p className="text-sm text-ink-secondary">{DISCLAIMER.humanReview}</p>
      </Card>

      {/* ── Model card ──────────────────────────────────────────────────── */}
      {validation === null ? (
        <Card eyebrow="Model" title="Model metrics unavailable">
          <p className="text-sm text-ink-secondary">
            The published metrics could not be loaded, so nothing is shown here.
            This page states what the model can and cannot do; printing another
            model&rsquo;s figures in place of the missing ones would defeat its
            purpose entirely.
          </p>
        </Card>
      ) : (
        <Card eyebrow="Model" title={validation.modelVersion}>
          <div className="flex flex-col gap-4">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
              <dt className="text-ink-secondary">Training blocks</dt>
              <dd className="text-right tabular-nums text-ink-primary" data-numeric>
                {formatNumber(validation.trainingTileCount, 'count')}
              </dd>

              <dt className="text-ink-secondary">Mean absolute error</dt>
              <dd className="text-right tabular-nums text-ink-primary" data-numeric>
                {validation.maeC.toFixed(2)} °C
              </dd>

              <dt className="text-ink-secondary">R²</dt>
              <dd className="text-right tabular-nums text-ink-primary" data-numeric>
                {validation.r2.toFixed(2)}
              </dd>

              <dt className="text-ink-secondary">Features used</dt>
              <dd className="text-right tabular-nums text-ink-primary" data-numeric>
                {validation.features.length}
              </dd>
            </dl>

            {/* The number that decides whether every other interval is believable. */}
            <div
              className={
                coverageIsHealthy
                  ? 'rounded-sharp border border-verified-line bg-verified-bg px-3 py-2'
                  : 'rounded-sharp border border-caution-line bg-caution-bg px-3 py-2'
              }
            >
              <div className="flex items-baseline justify-between">
                <span className="text-xs font-medium text-ink-primary">
                  Interval coverage
                </span>
                <span className="font-mono text-sm text-ink-primary" data-numeric>
                  {(validation.intervalCoverage * 100).toFixed(0)}%
                </span>
              </div>
              <p className="mt-1 text-xs text-ink-secondary">
                {/*
                  The measured figure, never the target. This branch used to print
                  "About 80% ... which is what a well-calibrated interval should
                  do" directly beneath a measured 93%, which was a false
                  reassurance contradicting the number above it.
                */}
                {coverageState === 'calibrated'
                  ? `${(validation.intervalCoverage * 100).toFixed(0)}% of held-out blocks fell inside the model's stated range, against the ${(coverageTarget * 100).toFixed(0)}% a calibrated interval should produce. The ranges shown across the site can be read as intended.`
                  : coverageState === 'conservative'
                    ? `${(validation.intervalCoverage * 100).toFixed(0)}% of held-out blocks fell inside the stated range, more than the ${(coverageTarget * 100).toFixed(0)}% a calibrated interval should produce. The ranges are wider than the model's own error warrants — cautious rather than overconfident, but not calibrated.`
                    : `Only ${(validation.intervalCoverage * 100).toFixed(0)}% of held-out blocks fell inside the stated range, against the ${(coverageTarget * 100).toFixed(0)}% a calibrated model should produce. The intervals shown across the site are narrower than the real uncertainty — treat every range as optimistic.`}
              </p>
            </div>

            <div className="flex flex-col gap-1.5">
              <span className="text-xs text-ink-secondary">Trained on</span>
              <p className="text-sm text-ink-primary">
                {validation.trainingDistricts.join(', ')}
              </p>
              <span className="mt-1 text-xs text-ink-secondary">
                Held out for testing
              </span>
              <p className="text-sm text-ink-primary">
                {validation.heldOutDistricts.join(', ')}
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* ── Limitations ─────────────────────────────────────────────────── */}
      {/* Two lists, deliberately. The methodology caveats hold for any version of
          the model; the model card's are specific to the one that produced these
          numbers. Merging them would let a version bump quietly drop a permanent
          caveat. */}
      <Card eyebrow="Limitations" title="What this tool cannot tell you">
        <ul className="flex flex-col gap-2.5">
          {DISCLAIMER.modelLimitations.map((limitation) => (
            <Limitation key={limitation} text={limitation} />
          ))}
        </ul>
      </Card>

      {validation !== null && (
        <>
        <Card
          eyebrow="Limitations"
          title={`Specific to ${validation.modelVersion}`}
        >
          <ul className="flex flex-col gap-2.5">
            {validation.limitations.map((limitation) => (
              <Limitation key={limitation} text={limitation} />
            ))}
          </ul>
        </Card>

        {/* ── Inputs ──────────────────────────────────────────────────────── */}
        <Card eyebrow="Inputs" title="Model features">
          <ul className="flex flex-wrap gap-1.5">
            {validation.features.map((feature) => (
              <li
                key={feature}
                className="rounded-sharp border border-line bg-subtle px-2 py-0.5 font-mono text-xs text-ink-secondary"
              >
                {feature}
              </li>
            ))}
          </ul>
        </Card>
        </>
      )}
    </div>
  );
}

function Limitation({ text }: { readonly text: string }) {
  return (
    <li className="flex items-start gap-2 text-sm">
      <span className="mt-0.5 shrink-0 text-ink-secondary">
        <Icon name="caution" size={14} />
      </span>
      <span className="text-ink-secondary">{text}</span>
    </li>
  );
}

function Step({
  n,
  title,
  body,
}: {
  readonly n: number;
  readonly title: string;
  readonly body: string;
}) {
  return (
    <li className="flex gap-3">
      <span
        className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border border-line bg-subtle font-mono text-[0.65rem] text-ink-secondary"
        aria-hidden="true"
      >
        {n}
      </span>
      <div className="flex flex-col gap-0.5">
        <span className="font-medium text-ink-primary">{title}</span>
        <span className="text-ink-secondary">{body}</span>
      </div>
    </li>
  );
}
