'use client';

import { LandCoverDonut } from '@/components/charts/LandCoverDonut';
import { ShapWaterfall } from '@/components/charts/ShapWaterfall';
import { ErrorState, Skeleton } from '@/components/feedback/States';
import { Button } from '@/components/ui/Button';
import { Estimate } from '@/components/ui/Estimate';
import { Icon } from '@/components/ui/Icon';
import { Tooltip } from '@/components/ui/Tooltip';
import { GLOSSARY } from '@/constants';
import { formatNumber, formatNumberMaybe } from '@/lib/format';
import type { Exposure, TileFeatures } from '@/types';

import { useAttributionDrawer } from './useAttributionDrawer';

interface AttributionDrawerProps {
  readonly projectId: string;
}

/**
 * Per-tile attribution overlay (SRS screen #4).
 *
 * Answers one question: *why is this block hot?* The SHAP waterfall gives the
 * model's decomposition, the donut gives the ground truth it was computed from,
 * and the exposure block gives who is affected.
 *
 * The anomaly is rendered through `<Estimate />`, which is the only sanctioned
 * renderer for a predicted value and always shows the interval. A drawer that
 * displayed "3.4 °C above the district" without its range would be the exact
 * false precision SRS §20.3 forbids.
 */
export function AttributionDrawer({ projectId }: AttributionDrawerProps) {
  const {
    isOpen,
    tileKey,
    attribution,
    features,
    exposure,
    isLoading,
    unavailableReason,
    errorMessage,
    onClose,
  } = useAttributionDrawer({ projectId });

  if (!isOpen || tileKey === null) return null;

  return (
    <>
      {/* Scrim. Click-to-close, but not focus-trapping: the map underneath stays
          legible, which is the point of a drawer rather than a modal. */}
      <div
        className="fixed inset-0 z-40 bg-ink-primary/20"
        onClick={onClose}
        aria-hidden="true"
      />

      <aside
        role="dialog"
        aria-modal="false"
        aria-label={`Heat drivers for block ${tileKey}`}
        className="fixed right-0 top-0 z-50 flex h-full w-full max-w-[26rem] flex-col border-l border-line bg-card"
      >
        <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <p className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
              Block
            </p>
            <h2 className="truncate font-mono text-sm text-ink-primary">{tileKey}</h2>
          </div>
          <Button
            variant="ghost"
            icon="close"
            onClick={onClose}
            aria-label="Close driver panel"
          >
            <span className="sr-only">Close</span>
          </Button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {isLoading && (
            <div className="flex flex-col gap-3">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          )}

          {errorMessage !== null && (
            <ErrorState
              message={errorMessage}
              hint="The temperature layers on the map are unaffected."
            />
          )}

          {unavailableReason !== null && (
            <p className="rounded-sharp border border-line bg-subtle p-3 text-sm text-ink-secondary">
              {unavailableReason}
            </p>
          )}

          {attribution !== null && (
            <div className="flex flex-col gap-6">
              {/* ── Anomaly ─────────────────────────────────────────────── */}
              <section className="flex flex-col gap-2">
                <div className="flex items-center gap-1.5">
                  <h3 className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
                    Above district average
                  </h3>
                  <Tooltip content={GLOSSARY.predictionInterval}>
                    <Icon name="info" size={13} />
                  </Tooltip>
                </div>
                <Estimate estimate={attribution.anomaly} size="hero" />
                <p className="text-xs text-ink-secondary">
                  Model {attribution.modelVersion}
                </p>
              </section>

              {/* ── Drivers ─────────────────────────────────────────────── */}
              <section className="flex flex-col gap-2">
                <div className="flex items-center gap-1.5">
                  <h3 className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
                    What makes it hot
                  </h3>
                  <Tooltip content={GLOSSARY.attribution}>
                    <Icon name="info" size={13} />
                  </Tooltip>
                </div>
                <ShapWaterfall drivers={attribution.drivers} />
                <p className="text-xs text-ink-secondary">
                  Contributions are the model’s decomposition of this block’s anomaly.
                  They explain the prediction, not the physical cause.
                </p>
              </section>

              {/* ── Land cover ──────────────────────────────────────────── */}
              {features !== null ? (
                <section className="flex flex-col gap-3">
                  <h3 className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
                    Ground cover
                  </h3>
                  <LandCoverDonut features={features} />
                  <FeatureList features={features} />
                </section>
              ) : (
                <section className="flex flex-col gap-2">
                  <h3 className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
                    Ground cover
                  </h3>
                  <p className="text-sm text-ink-secondary">
                    Land-cover detail is not available for this block.
                  </p>
                </section>
              )}

              {/* ── Exposure ────────────────────────────────────────────── */}
              {exposure !== null && <ExposureBlock exposure={exposure} />}
            </div>
          )}
        </div>
      </aside>
    </>
  );
}

/** Raw measured features, with "not measured" shown rather than hidden. */
function FeatureList({ features }: { readonly features: TileFeatures }) {
  const rows: readonly { label: string; value: string }[] = [
    { label: 'Tree canopy', value: pct(features.canopyPct) },
    { label: 'Paved surface', value: pct(features.imperviousPct) },
    { label: 'Buildings', value: pct(features.buildingPct) },
    {
      label: 'Distance to water',
      value:
        features.distToWaterM === null
          ? 'not measured'
          : `${formatNumber(features.distToWaterM, 'count')} m`,
    },
    {
      label: 'Elevation',
      value:
        features.elevationM === null
          ? 'not measured'
          : `${formatNumber(features.elevationM, 'count')} m`,
    },
  ];

  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
      {rows.map((row) => (
        <div key={row.label} className="contents">
          <dt className="text-ink-secondary">{row.label}</dt>
          <dd className="text-right tabular-nums text-ink-primary" data-numeric>
            {row.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function pct(value: number | null): string {
  return value === null ? 'not measured' : `${formatNumber(value, 'count')}%`;
}

function ExposureBlock({ exposure }: { readonly exposure: Exposure }) {
  const assets = Object.entries(exposure.assets).filter(([, count]) => count > 0);

  return (
    <section className="flex flex-col gap-3 border-t border-line pt-4">
      <h3 className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
        Who is exposed
      </h3>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
        <dt className="text-ink-secondary">Residents</dt>
        <dd className="text-right tabular-nums text-ink-primary" data-numeric>
          {formatNumberMaybe(exposure.population, 'people')}
        </dd>

        <dt className="text-ink-secondary">Over 65</dt>
        <dd className="text-right tabular-nums text-ink-primary" data-numeric>
          {exposure.pctOver65 === null
            ? '—'
            : `${formatNumber(exposure.pctOver65, 'count')}%`}
        </dd>

        <dt className="text-ink-secondary">Below poverty line</dt>
        <dd className="text-right tabular-nums text-ink-primary" data-numeric>
          {exposure.pctPoverty === null
            ? '—'
            : `${formatNumber(exposure.pctPoverty, 'count')}%`}
        </dd>

        <dt className="flex items-center gap-1 text-ink-secondary">
          Vulnerability
          <Tooltip content={SVI_HELP}>
            <Icon name="info" size={12} />
          </Tooltip>
        </dt>
        <dd className="text-right tabular-nums text-ink-primary" data-numeric>
          {/* Two decimals, not the shared `count` precision. SVI is a 0–1 index,
              so rounding to whole numbers renders 0.81 as "1" — which reads as
              maximum vulnerability rather than high vulnerability. */}
          {exposure.sviScore === null ? '—' : exposure.sviScore.toFixed(2)}
        </dd>
      </dl>

      {/* The resolution caveat sits beside the number, not in a footnote. */}
      {exposure.sviScore !== null && (
        <p className="text-xs text-ink-secondary">
          Vulnerability is published per census tract, coarser than this block, so
          it is shared with neighbouring blocks in the same tract.
        </p>
      )}

      {assets.length > 0 && (
        <p className="text-xs text-ink-secondary">
          Nearby:{' '}
          {assets
            .map(([name, count]) => `${count} ${humanise(name, count)}`)
            .join(', ')}
        </p>
      )}

      {exposure.population === null && (
        <p className="text-xs text-ink-secondary">
          Population is unavailable here, so this block carries no person-heat-hours
          in the ranking.
        </p>
      )}
    </section>
  );
}

const SVI_HELP =
  'CDC Social Vulnerability Index, 0 to 1. Higher means a population less able ' +
  'to cope with extreme heat.';

const ASSET_LABELS: Readonly<Record<string, readonly [string, string]>> = {
  busStop: ['bus stop', 'bus stops'],
  school: ['school', 'schools'],
  park: ['park', 'parks'],
  playground: ['playground', 'playgrounds'],
  hospital: ['hospital', 'hospitals'],
};

function humanise(key: string, count: number): string {
  const labels = ASSET_LABELS[key];
  if (labels === undefined) return key;
  return count === 1 ? labels[0] : labels[1];
}
