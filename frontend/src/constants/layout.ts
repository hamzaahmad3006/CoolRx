/**
 * CoolRx spacing, dimensions and layout constants.
 * 4px baseline (SRS §28.4). Never hardcode a pixel value in a component.
 */

/** 4px baseline scale. */
export const SPACING = {
  xs: '0.25rem', //  4px
  sm: '0.5rem', //  8px
  md: '1rem', // 16px
  lg: '1.5rem', // 24px
  xl: '2rem', // 32px
  xxl: '3rem', // 48px
} as const;

/** Application shell dimensions. */
export const SHELL = {
  /** Left navigation rail. */
  railWidth: 220,
  railWidthCollapsed: 64,
  /** Top bar. */
  topBarHeight: 56,
  /** Right analysis panel. */
  panelWidth: 380,
  /** Attribution drawer overlay. */
  drawerWidth: 420,
  /** Centred content column on the landing page. */
  contentMaxWidth: 1120,
  /** Wide layouts (plan table, portfolio table). */
  wideMaxWidth: 1440,
} as const;

/** Component dimensions. */
export const SIZE = {
  /** All buttons and inputs — high-density layouts. */
  controlHeight: 36,
  /** Data table rows. */
  tableRowHeight: 40,
  /** Square map controls. */
  mapControlSize: 32,
  /** Categorical legend swatch. */
  legendSwatch: 12,
  /** Tag / chip height. */
  tagHeight: 20,
  /** Card padding. */
  cardPadding: 20,
  /** Icon default. */
  iconSize: 16,
  iconSizeLarge: 20,
} as const;

/**
 * "Technical-sharp" — a single 4px radius everywhere, including large
 * containers. Stitch's output drifted to `rounded-full` in 35 places; pills are
 * not part of this system.
 */
export const RADIUS = {
  sharp: '0.25rem',
} as const;

/** Responsive breakpoints. Desktop-first — planners work on large monitors. */
export const BREAKPOINT = {
  /** Read-only below this. */
  mobile: 768,
  /** Map full width, panel becomes a bottom sheet. */
  tablet: 1280,
  /** Primary target: map + side panel. */
  desktop: 1440,
} as const;

/** Map rendering defaults. */
export const MAP_DEFAULTS = {
  /** Tile fill opacity so basemap streets stay faintly legible. */
  tileOpacity: 0.75,
  /** Selected-tile outline width in px. */
  selectionOutlineWidth: 2,
  /** Show tile borders only above this zoom — borders on thousands of tiles
   *  create moiré at district zoom. */
  tileBorderMinZoom: 15,
} as const;

/**
 * FortyGuard API constraints, mirrored client-side so an invalid request is
 * rejected before it can consume a credit (SRS FR-002).
 */
export const FG_LIMITS = {
  /** Basic / Startup plan AOI cap. 50 only if Premium is confirmed. */
  maxAoiSqMi: 10,
  /** The API accepts only these three granularity values. */
  granularityOptions: [60, 80, 100] as const,
  defaultGranularity: 80,
  /** Stricter of the two documented date floors (docs say 2019, FAQ says 2021). */
  dateFloor: '2021-01-01',
  /** Forecast horizon — hard API limit. */
  maxForecastHours: 12,
  /** Danger threshold default, in °C. */
  defaultThresholdC: 35,
  /** Exceedance-ladder steps above the threshold (SRS §9.4). */
  ladderSteps: 10,
} as const;

export type Granularity = (typeof FG_LIMITS.granularityOptions)[number];
