/**
 * CoolRx icon registry.
 *
 * Semantic role → lucide-react export name. Components reference the SEMANTIC
 * key (`ICONS.diagnosis`), never a library name directly, so swapping icon
 * libraries touches this one file.
 *
 * This module holds strings only — no React imports — so `constants/` stays
 * free of components. The string → component mapping lives in
 * `src/components/ui/Icon.tsx`.
 *
 * Why lucide-react and not Material Symbols: Stitch's output loaded the Material
 * Symbols Outlined web font from Google Fonts on every page. lucide-react ships
 * as tree-shaken SVG components — no runtime network fetch, no font-swap flash,
 * and it matches the "small line icons" direction in SRS §28.7.
 */

export const ICONS = {
  /* ── Navigation (left rail) ─────────────────────────────────────────────── */
  diagnosis: 'ChartColumn',
  priorities: 'ListOrdered',
  prescription: 'ClipboardList',
  beforeAfter: 'Columns2',
  impactEquity: 'Scale',
  actionPlan: 'FileText',
  verify: 'BadgeCheck',
  agentTrace: 'Activity',
  methods: 'BookOpen',
  portfolio: 'LayoutGrid',

  /* ── Workflow steps (landing process strip) ────────────────────────────── */
  measure: 'Thermometer',
  diagnose: 'Stethoscope',
  prescribe: 'Pill',
  verified: 'BadgeCheck',

  /* ── Analytic layers ──────────────────────────────────────────────────── */
  temperature: 'Thermometer',
  exceedance: 'Flame',
  persistence: 'Timer',
  peakHour: 'Clock',

  /* ── Intervention categories ──────────────────────────────────────────── */
  water: 'Droplets',
  green: 'Trees',
  shade: 'Umbrella',
  material: 'PaintRoller',

  /* ── Exposure assets ──────────────────────────────────────────────────── */
  population: 'Users',
  busStop: 'Bus',
  school: 'GraduationCap',
  park: 'Trees',
  hospital: 'Cross',
  vulnerability: 'Accessibility',

  /* ── Risk levels (paired with colour + word — never colour alone) ──────── */
  riskLow: 'Minus',
  riskModerate: 'ChevronUp',
  riskHigh: 'ChevronsUp',
  riskExtreme: 'TriangleAlert',

  /* ── Trust and provenance ─────────────────────────────────────────────── */
  provenance: 'Link2',
  estimate: 'Sigma',
  info: 'Info',
  caution: 'TriangleAlert',
  error: 'CircleAlert',
  help: 'CircleHelp',
  audit: 'ScrollText',

  /* ── Actions ──────────────────────────────────────────────────────────── */
  optimize: 'Sparkles',
  download: 'Download',
  copy: 'Copy',
  export: 'FileDown',
  search: 'Search',
  reset: 'RotateCcw',
  close: 'X',
  add: 'Plus',
  remove: 'Minus',
  forward: 'ArrowRight',
  back: 'ArrowLeft',
  expand: 'ChevronDown',
  collapse: 'ChevronUp',
  menu: 'Menu',
  placeAoi: 'Crosshair',
  calendar: 'CalendarCheck',

  /* ── Status ───────────────────────────────────────────────────────────── */
  queued: 'Clock',
  running: 'LoaderCircle',
  complete: 'CircleCheck',
  failed: 'CircleX',
  cached: 'Database',
  fixture: 'FlaskConical',
  credits: 'Coins',

  /* ── Theme ────────────────────────────────────────────────────────────── */
  darkMode: 'Moon',
  lightMode: 'Sun',

  /* ── Agent trace ──────────────────────────────────────────────────────── */
  nodeDeterministic: 'Braces',
  nodeLlm: 'Sparkles',
  guard: 'ShieldCheck',
  tokens: 'Cpu',
} as const;

export type IconName = keyof typeof ICONS;
export type LucideIconName = (typeof ICONS)[IconName];

/**
 * Original Google Stitch icon names (Material Symbols Outlined), kept for
 * traceability when porting a mockup. Left column is what appears in the Stitch
 * `code.html`; right column is the `ICONS` key that replaces it.
 */
export const STITCH_ICON_MIGRATION: Readonly<Record<string, IconName>> = {
  analytics: 'diagnosis',
  priority_high: 'riskExtreme',
  medical_services: 'prescribe',
  prescriptions: 'prescription',
  medication: 'prescribe',
  thermostat: 'temperature',
  local_fire_department: 'exceedance',
  timer: 'persistence',
  compare: 'beforeAfter',
  balance: 'impactEquity',
  description: 'actionPlan',
  verified: 'verify',
  timeline: 'agentTrace',
  event_available: 'calendar',
  groups: 'population',
  directions_bus: 'busStop',
  school: 'school',
  park: 'park',
  accessibility_new: 'vulnerability',
  format_paint: 'material',
  link: 'provenance',
  info: 'info',
  warning: 'caution',
  help: 'help',
  check_circle: 'complete',
  magic_button: 'optimize',
  download: 'download',
  content_copy: 'copy',
  search: 'search',
  close: 'close',
  add: 'add',
  remove: 'remove',
  arrow_forward: 'forward',
  menu: 'menu',
  my_location: 'placeAoi',
  dark_mode: 'darkMode',
  code_blocks: 'nodeDeterministic',
  data_object: 'nodeDeterministic',
  memory: 'tokens',
  tag: 'provenance',
} as const;
