'use client';

import { AoiMap } from '@/components/map/AoiMap';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Icon } from '@/components/ui/Icon';
import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { Tooltip } from '@/components/ui/Tooltip';
import { FG_LIMITS, GLOSSARY } from '@/constants';
import { formatNumber } from '@/lib/format';
import type { FgGranularity } from '@/types';

import { MAX_EDGE_KM, MIN_EDGE_KM, useAoiStudio } from './useAoiStudio';

/**
 * AOI Studio (SRS screen #2).
 *
 * Where a run is configured before any credit is spent. Every constraint the API
 * imposes is visible here and enforced before submit: the area cap, the US-only
 * coverage, the date floor, the three granularities.
 *
 * The area badge is the most important element on the page. It updates on every
 * change from a local calculation, then reconciles against the server's
 * authoritative figure once the slider settles — and while that is pending the
 * button says so rather than claiming a verdict the server has not given.
 */
export function AoiStudioPage() {
  const {
    box,
    edgeKm,
    startDate,
    startTime,
    granularity,
    thresholdC,
    buildLadder,
    localAreaSqMi,
    maxAreaSqMi,
    serverAreaSqMi,
    issues,
    isValid,
    isValidating,
    isUnconfirmed,
    estimatedTiles,
    estimatedCredits,
    isSubmitting,
    submitError,
    onRecenter,
    onEdgeKmChange,
    onStartDateChange,
    onStartTimeChange,
    onGranularityChange,
    onThresholdChange,
    onBuildLadderChange,
    onSubmit,
  } = useAoiStudio();

  const area = serverAreaSqMi ?? localAreaSqMi;
  const overCap = area > maxAreaSqMi;

  const panel = (
    <div className="flex flex-col gap-4">
      {/* ── Size ────────────────────────────────────────────────────────── */}
      <Card eyebrow="Area" title="Size and position">
        <div className="flex flex-col gap-4">
          <div>
            <div className="flex items-baseline justify-between">
              <label htmlFor="aoi-size" className="text-sm text-ink-secondary">
                Box size
              </label>
              <span className="font-mono text-sm text-ink-primary" data-numeric>
                {edgeKm.toFixed(1)} km
              </span>
            </div>
            <input
              id="aoi-size"
              type="range"
              min={MIN_EDGE_KM}
              max={MAX_EDGE_KM}
              step={0.1}
              value={edgeKm}
              onChange={(event) => onEdgeKmChange(Number(event.target.value))}
              className="mt-2 w-full accent-[var(--color-accent)]"
              aria-describedby="aoi-area-badge"
            />
          </div>

          {/* The badge that keeps a run inside the plan cap. */}
          <div
            id="aoi-area-badge"
            className={
              overCap
                ? 'flex items-baseline justify-between rounded-sharp border border-danger-line bg-danger-bg px-3 py-2'
                : 'flex items-baseline justify-between rounded-sharp border border-line bg-subtle px-3 py-2'
            }
          >
            <span className="text-sm text-ink-secondary">Area</span>
            <span
              className={
                overCap
                  ? 'font-mono text-sm font-medium text-danger'
                  : 'font-mono text-sm font-medium text-ink-primary'
              }
              data-numeric
            >
              {area.toFixed(2)} / {maxAreaSqMi} mi²
            </span>
          </div>

          <p className="text-xs text-ink-secondary">
            Click the map to move the area. The cap is set by our FortyGuard plan,
            not by the district.
          </p>
        </div>
      </Card>

      {/* ── When ────────────────────────────────────────────────────────── */}
      <Card eyebrow="Measurement" title="When to measure">
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <label htmlFor="aoi-date" className="text-xs text-ink-secondary">
                Date
              </label>
              <input
                id="aoi-date"
                type="date"
                value={startDate}
                min={FG_LIMITS.dateFloor}
                onChange={(event) => onStartDateChange(event.target.value)}
                className="rounded-sharp border border-line bg-card px-2 py-1.5 font-mono text-sm text-ink-primary"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="aoi-time" className="text-xs text-ink-secondary">
                Hour (UTC)
              </label>
              <input
                id="aoi-time"
                type="time"
                value={startTime}
                onChange={(event) => onStartTimeChange(event.target.value)}
                className="rounded-sharp border border-line bg-card px-2 py-1.5 font-mono text-sm text-ink-primary"
              />
            </div>
          </div>
          <p className="text-xs text-ink-secondary">
            History reaches back to {FG_LIMITS.dateFloor}; forecasts reach{' '}
            {FG_LIMITS.maxForecastHours} hours ahead.
          </p>
        </div>
      </Card>

      {/* ── Resolution and threshold ────────────────────────────────────── */}
      <Card eyebrow="Analysis" title="Resolution and threshold">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-ink-secondary">Block size</span>
              <Tooltip content={GLOSSARY.granularity}>
                <Icon name="info" size={12} />
              </Tooltip>
            </div>
            <SegmentedControl
              options={FG_LIMITS.granularityOptions.map((value) => ({
                value: String(value),
                label: `${value} m`,
              }))}
              value={String(granularity)}
              onChange={(value) =>
                onGranularityChange(Number(value) as FgGranularity)
              }
              label="Analysis block size"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="flex items-baseline justify-between">
              <div className="flex items-center gap-1.5">
                <label htmlFor="aoi-threshold" className="text-xs text-ink-secondary">
                  Danger threshold
                </label>
                <Tooltip content={GLOSSARY.threshold}>
                  <Icon name="info" size={12} />
                </Tooltip>
              </div>
              <span className="font-mono text-sm text-ink-primary" data-numeric>
                {thresholdC} °C
              </span>
            </div>
            <input
              id="aoi-threshold"
              type="range"
              min={25}
              max={50}
              step={1}
              value={thresholdC}
              onChange={(event) => onThresholdChange(Number(event.target.value))}
              className="w-full accent-[var(--color-accent)]"
            />
          </div>

          <label className="flex items-start gap-2 text-xs text-ink-secondary">
            <input
              type="checkbox"
              checked={buildLadder}
              onChange={(event) => onBuildLadderChange(event.target.checked)}
              className="mt-0.5 accent-[var(--color-accent)]"
            />
            <span>
              Build the exceedance ladder — {FG_LIMITS.ladderSteps + 1} extra
              measurements that convert predicted cooling into hours of danger
              avoided. Without it, impact is reported in degrees only.
            </span>
          </label>
        </div>
      </Card>

      {/* ── Cost ────────────────────────────────────────────────────────── */}
      <Card eyebrow="Before you run" title="What this will cost">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
          <dt className="text-ink-secondary">Blocks analysed</dt>
          <dd className="text-right tabular-nums text-ink-primary" data-numeric>
            about {formatNumber(estimatedTiles, 'count')}
          </dd>
          <dt className="text-ink-secondary">API calls</dt>
          <dd className="text-right tabular-nums text-ink-primary" data-numeric>
            {estimatedCredits}
          </dd>
        </dl>
      </Card>

      {/* ── Problems ────────────────────────────────────────────────────── */}
      {issues.length > 0 && (
        <ul className="flex flex-col gap-2">
          {issues.map((issue) => (
            <li
              key={`${issue.code}-${issue.field}`}
              className="flex items-start gap-2 rounded-sharp border border-danger-line bg-danger-bg px-3 py-2 text-xs text-danger"
            >
              <Icon name="caution" size={14} />
              <span>{issue.message}</span>
            </li>
          ))}
        </ul>
      )}

      {submitError !== null && (
        <p className="rounded-sharp border border-danger-line bg-danger-bg px-3 py-2 text-xs text-danger">
          {submitError}
        </p>
      )}

      <Button
        variant="primary"
        icon="diagnose"
        disabled={!isValid || isSubmitting || isValidating}
        onClick={onSubmit}
        className="w-full justify-center"
      >
        {isSubmitting
          ? 'Starting…'
          : isValidating
            ? 'Checking area…'
            : 'Run analysis'}
      </Button>

      {/* Said plainly rather than implied by a disabled button: the local figure
          is an estimate and the server has the final word. */}
      {isUnconfirmed && isValid && !isValidating && (
        <p className="text-xs text-ink-secondary">
          Area shown is a local estimate. The server checks it exactly before the
          run starts.
        </p>
      )}
    </div>
  );

  // Deliberately not `AppShell`. The Studio runs *before* a project exists, and
  // AppShell's rail builds per-project links — it would emit `/p//diagnose`.
  // A standalone frame is honest about there being nothing to navigate yet.
  return (
    <div className="flex h-dvh flex-col bg-background">
      <header className="flex shrink-0 items-baseline gap-3 border-b border-line bg-card px-5 py-3">
        <a href="/" className="font-medium text-ink-primary hover:underline">
          CoolRx
        </a>
        <span className="text-ink-muted" aria-hidden="true">
          /
        </span>
        <h1 className="text-sm text-ink-secondary">Set up an analysis</h1>
      </header>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div className="relative min-h-[18rem] flex-1">
          <AoiMap box={box} isInvalid={!isValid} onRecenter={onRecenter} />
        </div>

        <div className="w-full shrink-0 overflow-y-auto border-t border-line bg-background p-4 lg:w-[24rem] lg:border-l lg:border-t-0">
          {panel}
        </div>
      </div>
    </div>
  );
}
