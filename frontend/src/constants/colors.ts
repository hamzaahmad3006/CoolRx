/**
 * CoolRx colour system — the single source of truth.
 *
 * Never hardcode a colour in a component. Import from here, or use the Tailwind
 * utility backed by the matching CSS variable in `src/app/globals.css`.
 *
 * Two provenances are deliberately kept separate:
 *
 *  1. UI / SURFACE tokens — carried over from the Google Stitch `DESIGN.md`
 *     output so the built app matches the approved mockups.
 *
 *  2. DATA-VISUALISATION scales — authored here. Stitch's generated token set
 *     contained no data scales at all, and its pages fell back to mapping
 *     "hot" onto the semantic error red and "cool" onto a Material green.
 *     That is a red–green scale, which SRS §28.2 forbids because it is
 *     illegible to red–green colour-blind users (~8% of men). The scales below
 *     replace it with perceptually uniform, colour-blind-safe ramps.
 *
 * Rule: the accent colour is for interactive affordances ONLY. It never encodes
 * data. Semantic colours (error/caution) never encode data either.
 */

/* ─────────────────────────────────────────────────────────────────────────────
 * SURFACES & TEXT — light theme (primary)
 * ────────────────────────────────────────────────────────────────────────────*/
export const SURFACE = {
  /** Layer 0 — the app canvas. */
  background: '#F7F7F5',
  /** Layer 1 — cards and containers. */
  card: '#FFFFFF',
  /** Layer 2 — raised rows, hover fills. */
  subtle: '#F0F0EE',
  /** Inset wells, table headers. */
  inset: '#EFEDF0',
  /** Hairline borders. Hierarchy comes from these, never from shadows. */
  border: '#E2E1DC',
  /** Stronger border for overlays and modals (focus without elevation). */
  borderStrong: '#17181A',
  /** Inverted surface for tooltips. */
  inverse: '#17181A',
  onInverse: '#F2F0F3',
} as const;

export const TEXT = {
  primary: '#17181A',
  secondary: '#42474C',
  /** Non-essential only — do not use for values a user must read. */
  muted: '#73787D',
  onAccent: '#FFFFFF',
} as const;

/* ─────────────────────────────────────────────────────────────────────────────
 * INTERACTIVE ACCENT — controls, links, focus. NEVER data.
 * ────────────────────────────────────────────────────────────────────────────*/
export const ACCENT = {
  base: '#2B4A61',
  hover: '#1F3849',
  /** Deepest tone — page titles, active nav labels. */
  strong: '#123349',
  /** Tinted background for active nav items and selected segments. */
  subtle: '#EDF1F4',
  /** Focus ring. */
  focus: '#2B4A61',
} as const;

/* ─────────────────────────────────────────────────────────────────────────────
 * SEMANTIC — status only. Never used to encode a measured value.
 * ────────────────────────────────────────────────────────────────────────────*/
export const SEMANTIC = {
  errorText: '#A3231F',
  errorBg: '#FBEDEC',
  errorBorder: '#EFC9C6',
  /** "Degraded" / cached-data / caution. */
  cautionText: '#B4690E',
  cautionBg: '#FDF3E3',
  cautionBorder: '#F0DCB4',
  verifiedText: '#2E6B4F',
  verifiedBg: '#EBF3EE',
  verifiedBorder: '#C9DED2',
} as const;

/* ─────────────────────────────────────────────────────────────────────────────
 * HEAT SCALE — sequential, perceptually uniform, colour-blind safe.
 *
 * Magma family. Ordered coolest → hottest. Used for temperature, exceedance
 * hours, persistence hours and peak-hour maps.
 * ────────────────────────────────────────────────────────────────────────────*/
export const HEAT_SCALE = [
  '#FCFDBF',
  '#FEC98D',
  '#FD9668',
  '#F1605D',
  '#B63679',
  '#721F81',
  '#2D1160',
] as const;

/* ─────────────────────────────────────────────────────────────────────────────
 * COOLING SCALE (ΔT) — diverging, centred on zero.
 *
 * Deliberately a different hue family from HEAT_SCALE so that "hot" and
 * "cooled" can never be visually confused on the before/after view.
 * Ordered: strongest cooling → zero → warming.
 * ────────────────────────────────────────────────────────────────────────────*/
export const COOLING_SCALE = [
  '#0E7C86',
  '#6FB7BD',
  '#E8E6DF',
  '#E0B278',
  '#B5651D',
] as const;

/** Index of the zero midpoint in COOLING_SCALE. */
export const COOLING_SCALE_ZERO_INDEX = 2;

/* ─────────────────────────────────────────────────────────────────────────────
 * INTERVENTION CATEGORIES — FortyGuard's own four cooling mechanisms.
 *
 * Used in plan tables, legends and site markers ONLY. Never on the heat map,
 * where they would collide with the heat scale.
 * ────────────────────────────────────────────────────────────────────────────*/
export const INTERVENTION_COLORS = {
  water: '#3E7CA6',
  green: '#5C8A4A',
  shade: '#7A6EA3',
  material: '#A8814E',
} as const;

/* ─────────────────────────────────────────────────────────────────────────────
 * LAND COVER
 *
 * Categorical, for the attribution drawer's composition donut. Deliberately
 * muted and distinct from HEAT_SCALE: the donut sits beside the heat map, and a
 * warm-ramp colour here would read as a temperature.
 *
 * `unknown` is a hatched grey, not a slice colour. A tile whose land cover is
 * unmeasured must look unmeasured — filling the remainder with a real category
 * would fabricate composition data (SRS FR-008).
 * ────────────────────────────────────────────────────────────────────────────*/
export const LAND_COVER_COLORS = {
  canopy: '#4F7A4A',
  grassShrub: '#8FA96B',
  water: '#3E7CA6',
  building: '#8C8377',
  impervious: '#B0AAA1',
  unknown: '#D8D5CF',
} as const;

export type LandCoverKey = keyof typeof LAND_COVER_COLORS;

/* ─────────────────────────────────────────────────────────────────────────────
 * SHAP ATTRIBUTION
 *
 * A driver either pushes a tile hotter or cooler. Two colours only — using the
 * heat ramp here would imply a temperature value rather than a contribution.
 * ────────────────────────────────────────────────────────────────────────────*/
export const ATTRIBUTION_COLORS = {
  warming: '#C1611F',
  cooling: '#2F7A72',
  neutral: '#B8B4AC',
} as const;

/* ─────────────────────────────────────────────────────────────────────────────
 * RISK LEVELS
 *
 * Per SRS §28.7 a risk level is ALWAYS rendered as colour + icon + word.
 * Colour alone is never sufficient. The icon name refers to `ICONS.risk` in
 * `./icons.ts`.
 * ────────────────────────────────────────────────────────────────────────────*/
export const RISK_COLORS = {
  low: '#4C7A5D',
  moderate: '#B4890E',
  high: '#C1611F',
  extreme: '#9B2C2C',
} as const;

/* ─────────────────────────────────────────────────────────────────────────────
 * DARK THEME — SRS §28.1 marks this P2. Data scales are intentionally
 * identical across themes so a screenshot means the same thing in both.
 * ────────────────────────────────────────────────────────────────────────────*/
export const DARK = {
  background: '#121316',
  card: '#1B1D21',
  subtle: '#22252A',
  border: '#2C2F34',
  textPrimary: '#EDEDEA',
  textSecondary: '#A2A6AC',
} as const;

/* ─────────────────────────────────────────────────────────────────────────────
 * MAP CHROME
 * ────────────────────────────────────────────────────────────────────────────*/
export const MAP = {
  /** Basemap street lines — deliberately low contrast so data dominates. */
  street: '#D8D7D2',
  /** Selected tile outline. Selection NEVER changes a tile's fill, because
   *  that would corrupt the value encoding (SRS §28.8). */
  selectionOutline: '#17181A',
  /** Control-tile hatch on the verification map. */
  controlHatch: '#8A8D91',
  /** Default fill opacity so basemap streets stay faintly legible. */
  tileFillOpacity: 0.75,
} as const;

/* ─────────────────────────────────────────────────────────────────────────────
 * Derived types
 * ────────────────────────────────────────────────────────────────────────────*/
export type InterventionCategory = keyof typeof INTERVENTION_COLORS;
export type RiskLevel = keyof typeof RISK_COLORS;
export type HeatScaleStop = (typeof HEAT_SCALE)[number];
export type CoolingScaleStop = (typeof COOLING_SCALE)[number];

export const COLORS = {
  surface: SURFACE,
  text: TEXT,
  accent: ACCENT,
  semantic: SEMANTIC,
  heatScale: HEAT_SCALE,
  coolingScale: COOLING_SCALE,
  intervention: INTERVENTION_COLORS,
  risk: RISK_COLORS,
  dark: DARK,
  map: MAP,
} as const;
