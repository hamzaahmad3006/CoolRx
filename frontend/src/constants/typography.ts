/**
 * CoolRx typography scale.
 *
 * Exactly five UI sizes plus one report size (SRS §28.3). Do not add a sixth —
 * Stitch's output drifted to a `table-data: 14px` size; table cells use
 * `body` (15px) here instead.
 *
 * Tailwind equivalents live in `globals.css` as `text-eyebrow`, `text-caption`,
 * `text-body`, `text-heading`, `text-title`, `text-report`.
 */

export const FONT_FAMILY = {
  /** All functional interface text. */
  sans: 'var(--font-inter), ui-sans-serif, system-ui, sans-serif',
  /** Machine-readable values: activity IDs, tile keys, coordinates, correlation
   *  IDs. Distinguishes machine data from human labels. */
  mono: 'var(--font-jetbrains-mono), ui-monospace, monospace',
  /** Long-form report/PDF body only. A serif reads as a document rather than a
   *  screen — the correct register for a procurement artifact. */
  serif: 'var(--font-source-serif), Georgia, serif',
} as const;

export const TYPE = {
  title: {
    fontSize: '1.75rem',
    lineHeight: '2.25rem',
    fontWeight: 600,
    letterSpacing: '-0.02em',
    className: 'text-title font-semibold',
  },
  heading: {
    fontSize: '1.25rem',
    lineHeight: '1.75rem',
    fontWeight: 600,
    letterSpacing: '-0.01em',
    className: 'text-heading font-semibold',
  },
  body: {
    fontSize: '0.9375rem',
    lineHeight: '1.375rem',
    fontWeight: 400,
    letterSpacing: 'normal',
    className: 'text-body',
  },
  caption: {
    fontSize: '0.8125rem',
    lineHeight: '1.125rem',
    fontWeight: 400,
    letterSpacing: 'normal',
    className: 'text-caption',
  },
  /** Small-caps section label above a heading. */
  eyebrow: {
    fontSize: '0.75rem',
    lineHeight: '1rem',
    fontWeight: 600,
    letterSpacing: '0.08em',
    className: 'text-eyebrow font-semibold uppercase tracking-[0.08em]',
  },
  /** Monospace identifiers. */
  identifier: {
    fontSize: '0.8125rem',
    lineHeight: '1rem',
    fontWeight: 400,
    letterSpacing: 'normal',
    className: 'text-caption font-mono',
  },
  /** Serif — report and PDF body copy only. */
  report: {
    fontSize: '1rem',
    lineHeight: '1.5rem',
    fontWeight: 400,
    letterSpacing: 'normal',
    className: 'text-report font-serif',
  },
} as const;

export type TypeToken = keyof typeof TYPE;

/** Google Fonts families to load in `app/layout.tsx` via `next/font/google`. */
export const FONT_LOADS = {
  inter: { weights: ['400', '500', '600'] },
  jetBrainsMono: { weights: ['400'] },
  sourceSerif4: { weights: ['400', '600'] },
} as const;
