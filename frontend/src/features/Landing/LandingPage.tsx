'use client';

import { BRAND, SHELL } from '@/constants';
import { Button } from '@/components/ui/Button';
import { Icon } from '@/components/ui/Icon';
import { useLanding } from './useLanding';

/**
 * Landing page — UI only. All behaviour lives in `useLanding`.
 *
 * Ported from the Google Stitch "Landing Page" mockup, with three corrections:
 * the drop shadow and gradient overlay on the preview panel are removed
 * (SRS §28.1 forbids both), and the design tokens come from `@/constants`
 * rather than Stitch's Material-3 names.
 */
export function LandingPage() {
  const { presets, workflow, openDistrict, openMethods } = useLanding();

  return (
    <div
      className="mx-auto flex min-h-screen flex-col px-4 md:px-8"
      style={{ maxWidth: SHELL.contentMaxWidth }}
    >
      {/* ── Top bar ──────────────────────────────────────────────────────── */}
      <header className="flex h-16 items-center justify-between border-b border-line">
        <div className="flex items-baseline gap-2">
          <span className="text-heading font-semibold text-accent-strong">
            {BRAND.name}
          </span>
        </div>

        <nav className="flex items-center gap-6">
          <button
            type="button"
            onClick={openMethods}
            className="text-caption text-ink transition-colors hover:text-accent"
          >
            Methods
          </button>
          <a
            href="https://github.com"
            className="text-caption text-ink transition-colors hover:text-accent"
          >
            GitHub
          </a>
          <Button
            variant="primary"
            onClick={() => {
              const first = presets[0];
              if (first !== undefined) openDistrict(first.presetId);
            }}
          >
            Open a district
          </Button>
        </nav>
      </header>

      <main className="flex flex-1 flex-col gap-12 py-16">
        {/* ── Hero ───────────────────────────────────────────────────────── */}
        <section className="flex max-w-3xl flex-col gap-5">
          <h1 className="text-title font-semibold text-accent-strong">
            {BRAND.heroHeadline}
          </h1>
          <p className="text-body text-ink-secondary">{BRAND.heroSubline}</p>

          <div className="mt-2 flex items-center gap-3">
            <Button
              variant="primary"
              onClick={() => {
                const first = presets[0];
                if (first !== undefined) openDistrict(first.presetId);
              }}
            >
              Load Phoenix district
            </Button>
            <Button variant="secondary" onClick={openMethods}>
              How it works
            </Button>
          </div>
        </section>

        {/* ── Workflow strip ─────────────────────────────────────────────── */}
        <section className="rounded-sharp border border-line bg-card">
          <ol className="grid grid-cols-1 divide-y divide-line sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4 lg:divide-x">
            {workflow.map((step) => (
              <li key={step.label} className="flex flex-col gap-2 p-5">
                <Icon name={step.icon} size={20} className="text-accent" />
                <p className="text-eyebrow uppercase tracking-[0.08em] text-ink">
                  {step.label}
                </p>
                <p className="text-caption text-ink-secondary">{step.caption}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* ── Preset districts ───────────────────────────────────────────── */}
        <section className="flex flex-col gap-4">
          <div>
            <p className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
              Pre-analysed districts
            </p>
            <h2 className="mt-1 text-heading font-semibold text-accent-strong">
              Open a district
            </h2>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {presets.map((preset) => (
              <button
                key={preset.presetId}
                type="button"
                onClick={() => openDistrict(preset.presetId)}
                className="group flex flex-col gap-4 rounded-sharp border border-line bg-card p-5 text-left transition-colors hover:bg-subtle"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="text-heading font-semibold text-accent-strong">
                      {preset.name}
                    </h3>
                    <p className="text-caption text-ink-secondary">
                      {preset.city}, {preset.state}
                    </p>
                  </div>
                  <Icon
                    name="forward"
                    className="text-ink-muted transition-colors group-hover:text-accent"
                  />
                </div>

                <dl className="grid grid-cols-2 gap-3">
                  <Stat
                    label="Peak temp"
                    value={`${preset.peakTempC.toFixed(1)} °C`}
                  />
                  <Stat
                    label="Hours > 35 °C"
                    value={String(preset.hoursAboveThreshold)}
                  />
                  <div className="col-span-2">
                    <Stat
                      label="Population"
                      value={preset.population.toLocaleString('en-US')}
                    />
                  </div>
                </dl>
              </button>
            ))}
          </div>
        </section>
      </main>

      {/* ── Footer ───────────────────────────────────────────────────────── */}
      <footer className="mt-auto border-t border-line py-6">
        <p className="text-caption text-ink-secondary">{BRAND.tagline}</p>
        <p className="mt-1 text-caption text-ink-muted">{BRAND.attribution}</p>
      </footer>
    </div>
  );
}

interface StatProps {
  readonly label: string;
  readonly value: string;
}

function Stat({ label, value }: StatProps) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
        {label}
      </dt>
      <dd className="font-mono text-caption text-ink" data-numeric>
        {value}
      </dd>
    </div>
  );
}
