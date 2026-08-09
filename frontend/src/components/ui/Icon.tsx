import {
  Accessibility, Activity, ArrowLeft, ArrowRight, BadgeCheck, BookOpen, Braces,
  Bus, CalendarCheck, ChartColumn, ChevronDown, ChevronsUp, ChevronUp,
  CircleAlert, CircleCheck, CircleHelp, CircleX, ClipboardList, Clock, Coins,
  Columns2, Copy, Cpu, Crosshair, Cross, Database, Download, Droplets, FileDown,
  FileText, FlaskConical, Flame, GraduationCap, Info, LayoutGrid, Link2, ListOrdered,
  LoaderCircle, Menu, Minus, Moon, PaintRoller, Pill, Plus, RotateCcw, Scale,
  ScrollText, Search, ShieldCheck, Sigma, Sparkles, Stethoscope, Sun,
  Thermometer, Timer, Trees, TriangleAlert, Umbrella, Users, X,
  type LucideIcon,
} from 'lucide-react';

import { ICONS, SIZE, type IconName } from '@/constants';
import { cn } from '@/lib/cn';

/**
 * Semantic icon component.
 *
 * Components reference a semantic role (`<Icon name="exceedance" />`), never a
 * library export. Swapping icon libraries touches only this file and
 * `constants/icons.ts`.
 */
const REGISTRY: Readonly<Record<IconName, LucideIcon>> = {
  // Navigation
  diagnosis: ChartColumn,
  priorities: ListOrdered,
  prescription: ClipboardList,
  beforeAfter: Columns2,
  impactEquity: Scale,
  actionPlan: FileText,
  verify: BadgeCheck,
  agentTrace: Activity,
  methods: BookOpen,
  portfolio: LayoutGrid,
  // Workflow
  measure: Thermometer,
  diagnose: Stethoscope,
  prescribe: Pill,
  verified: BadgeCheck,
  // Analytic layers
  temperature: Thermometer,
  exceedance: Flame,
  persistence: Timer,
  peakHour: Clock,
  // Intervention categories
  water: Droplets,
  green: Trees,
  shade: Umbrella,
  material: PaintRoller,
  // Exposure
  population: Users,
  busStop: Bus,
  school: GraduationCap,
  park: Trees,
  hospital: Cross,
  vulnerability: Accessibility,
  // Risk
  riskLow: Minus,
  riskModerate: ChevronUp,
  riskHigh: ChevronsUp,
  riskExtreme: TriangleAlert,
  // Trust
  provenance: Link2,
  estimate: Sigma,
  info: Info,
  caution: TriangleAlert,
  error: CircleAlert,
  help: CircleHelp,
  audit: ScrollText,
  // Actions
  optimize: Sparkles,
  download: Download,
  copy: Copy,
  export: FileDown,
  search: Search,
  reset: RotateCcw,
  close: X,
  add: Plus,
  remove: Minus,
  forward: ArrowRight,
  back: ArrowLeft,
  expand: ChevronDown,
  collapse: ChevronUp,
  menu: Menu,
  placeAoi: Crosshair,
  calendar: CalendarCheck,
  // Status
  queued: Clock,
  running: LoaderCircle,
  complete: CircleCheck,
  failed: CircleX,
  cached: Database,
  fixture: FlaskConical,
  credits: Coins,
  // Theme
  darkMode: Moon,
  lightMode: Sun,
  // Agent
  nodeDeterministic: Braces,
  nodeLlm: Sparkles,
  guard: ShieldCheck,
  tokens: Cpu,
};

interface IconProps {
  readonly name: IconName;
  /** Pixel size. Defaults to the 16px interface icon size. */
  readonly size?: number;
  readonly className?: string;
  /** Decorative by default. Provide a label when the icon carries meaning. */
  readonly label?: string;
  readonly strokeWidth?: number;
}

export function Icon({
  name,
  size = SIZE.iconSize,
  className,
  label,
  strokeWidth = 1.75,
}: IconProps) {
  const Component = REGISTRY[name];
  const isDecorative = label === undefined;

  return (
    <Component
      width={size}
      height={size}
      strokeWidth={strokeWidth}
      className={cn('shrink-0', className)}
      aria-hidden={isDecorative}
      aria-label={label}
      role={isDecorative ? undefined : 'img'}
    />
  );
}

/** The underlying lucide export name, for debugging and the Stitch migration map. */
export function lucideNameFor(name: IconName): string {
  return ICONS[name];
}
