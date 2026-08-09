'use client';

import { formatHours, formatNumber, formatPercentScaled } from '@/lib/format';
import { AppShell } from '@/components/layout/AppShell';
import { DeltaHistogram } from '@/components/charts/DeltaHistogram';
import { MapLegend } from '@/components/map/MapLegend';
import { SwipeCompareMap } from '@/components/map/SwipeCompareMap';
import { ErrorState, Skeleton } from '@/components/feedback/States';
import { Estimate } from '@/components/ui/Estimate';
import { Icon } from '@/components/ui/Icon';
import { StatTile } from '@/components/ui/StatTile';
import { useBeforeAfter } from './useBeforeAfter';

interface BeforeAfterPageProps {
  readonly projectId: string;
  readonly planId: string;
  readonly districtName: string;
  readonly districtContext: string;
}

/**
 * Before/After — the comparison that makes the plan legible in three seconds.
 *
 * The one non-negotiable constraint: both sides of the divider render on a single
 * shared colour domain, stated in the legend. A per-side scale would make the
 * predicted field look cooler than it is (SRS §28.8).
 */
export function BeforeAfterPage({
  projectId,
  planId,
  districtName,
  districtContext,
}: BeforeAfterPageProps) {
  const {
    before,
    after,
    sharedDomain,
    meanDelta,
    heatHoursAvoided,
    personHeatHoursAvoided,
    peopleReached,
    pctTopSviQuartile,
    treatedTileCount,
    deltaBins,
    maxAbsDelta,
    center,
    swipePosition,
    isLoading,
    errorMessage,
    estimateDisclaimer,
    onSwipeChange,
  } = useBeforeAfter({ planId });

  return (
    <AppShell
      projectId={projectId}
      districtName={districtName}
      districtContext={districtContext}
      breadcrumb={[districtName, 'Before / After']}
      degradedReason="fixture"
    >
      <div className="flex h-full flex-col">
        {/* ── Map ───────────────────────────────────────────────────────── */}
        <div className="relative min-h-0 flex-1">
          {errorMessage !== null ? (
            <div className="p-6">
              <ErrorState
                message={errorMessage}
                hint="The plan itself is unaffected — try reloading."
              />
            </div>
          ) : before === null || after === null || isLoading ? (
            <Skeleton className="size-full rounded-none" />
          ) : (
            <>
              <SwipeCompareMap
                before={before}
                after={after}
                sharedDomain={sharedDomain}
                position={swipePosition}
                onPositionChange={onSwipeChange}
                center={center}
              />

              {/* One legend, because there is one scale. */}
              <div className="pointer-events-none absolute bottom-4 right-4">
                <MapLegend
                  title="Temperature at 2 m"
                  domain={sharedDomain}
                  unit="celsius"
                  unitLabel="°C"
                />
                <p className="mt-1 max-w-56 text-caption text-ink-muted">
                  Shared scale {sharedDomain[0]}–{sharedDomain[1]} °C — identical
                  colours mean identical temperatures on both sides.
                </p>
              </div>
            </>
          )}
        </div>

        {/* ── Impact bar ────────────────────────────────────────────────── */}
        <div className="shrink-0 border-t border-line bg-canvas p-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[repeat(4,minmax(0,1fr))_1.2fr]">
            <StatTile
              label="Mean cooling"
              icon="temperature"
              detail={`Across ${formatNumber(treatedTileCount, 'count')} treated blocks`}
              onShowProvenance={() => undefined}
            >
              <Estimate estimate={meanDelta} size="hero" />
            </StatTile>

            <StatTile
              label="Heat-hours avoided"
              icon="exceedance"
              onShowProvenance={() => undefined}
            >
              {formatHours(heatHoursAvoided)}
            </StatTile>

            <StatTile
              label="Person-heat-hours"
              icon="population"
              detail="People multiplied by dangerous hours avoided"
              onShowProvenance={() => undefined}
            >
              {formatNumber(personHeatHoursAvoided, 'person_hour')}
            </StatTile>

            <StatTile
              label="People reached"
              icon="vulnerability"
              detail={`${formatPercentScaled(pctTopSviQuartile)} in the most vulnerable quartile`}
              onShowProvenance={() => undefined}
            >
              {formatNumber(peopleReached, 'people')}
            </StatTile>

            <div className="flex flex-col gap-2 rounded-sharp border border-line bg-card p-5">
              <p className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
                Predicted change
              </p>
              {deltaBins.length === 0 ? (
                <Skeleton className="h-32" />
              ) : (
                <DeltaHistogram bins={deltaBins} maxAbsDelta={maxAbsDelta} />
              )}
            </div>
          </div>

          {/* Required disclaimer, adjacent to the figures it qualifies. */}
          <p className="mt-3 flex items-start gap-2 rounded-sharp border border-caution-line bg-caution-bg px-4 py-2.5 text-caption text-caution">
            <Icon name="caution" size={14} className="mt-0.5" />
            {estimateDisclaimer}
          </p>
        </div>
      </div>
    </AppShell>
  );
}
