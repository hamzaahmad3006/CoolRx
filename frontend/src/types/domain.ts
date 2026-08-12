/**
 * CoolRx domain model — mirrors the PostGIS schema in SRS §13.
 *
 * Strict TypeScript: no `any`, no `unknown`. Where a value is genuinely a map of
 * numbers (SHAP contributions, asset counts) it is typed as an explicit
 * `Record<K, number>` rather than loosened.
 */

import type {
  FgAnalyticType,
  FgDirection,
  FgGranularity,
  FgFilterType,
  FgFeatureCollection,
  FgStatsData,
  FgTileProperties,
  FgUnits,
} from './fortyguard';
import type { InterventionCategory, RiskLevel } from '@/constants/colors';

/* ═════════════════════════════════════════════════════════════════════════════
 * THE ESTIMATE TYPE
 *
 * The most important type in the codebase. SRS §20.3 forbids displaying a
 * predicted value without its uncertainty interval, and §9.2.8 makes that a
 * type-level guarantee rather than a convention: `ciLow` and `ciHigh` are
 * REQUIRED. A bare point estimate is unrepresentable.
 *
 * Only `<Estimate />` may render one.
 * ════════════════════════════════════════════════════════════════════════════*/
export interface Estimate {
  /** Point estimate (p50). */
  readonly value: number;
  /** Lower prediction bound (p10). Required — never optional. */
  readonly ciLow: number;
  /** Upper prediction bound (p90). Required — never optional. */
  readonly ciHigh: number;
  readonly unit: EstimateUnit;
  /** Model version that produced it, for provenance. */
  readonly modelVersion: string;
}

export type EstimateUnit =
  | 'celsius'
  | 'hour'
  | 'person_hour'
  | 'usd'
  | 'people'
  | 'count';

/* ═════════════════════════════════════════════════════════════════════════════
 * PROJECT & AREA OF INTEREST
 * ════════════════════════════════════════════════════════════════════════════*/
export interface Project {
  readonly id: string;
  readonly name: string;
  readonly city: string;
  /** Two-letter US state code — coverage is United States only. */
  readonly state: string;
  readonly aoi: FgFeatureCollection;
  readonly areaSqMi: number;
  readonly isPreset: boolean;
  readonly createdAt: string;
}

export interface AoiDraft {
  readonly centerLat: number;
  readonly centerLon: number;
  /** Box edge length in kilometres. */
  readonly sizeKm: number;
  readonly areaSqMi: number;
}

/** Result of client-side pre-flight validation (SRS FR-002). */
export interface AoiValidation {
  readonly isValid: boolean;
  readonly violations: readonly AoiViolation[];
}

export type AoiViolationCode =
  | 'AOI_AREA_EXCEEDED'
  | 'AOI_OUTSIDE_COVERAGE'
  | 'AOI_NOT_CLOSED'
  | 'AOI_INVALID_GEOMETRY'
  | 'DATE_BELOW_FLOOR'
  | 'DATE_BEYOND_FORECAST'
  | 'GRANULARITY_INVALID'
  | 'FILTER_TYPE_INVALID';

export interface AoiViolation {
  readonly code: AoiViolationCode;
  readonly message: string;
  readonly field: string;
}

/* ═════════════════════════════════════════════════════════════════════════════
 * MEASUREMENT
 * ════════════════════════════════════════════════════════════════════════════*/
export interface MeasurementWindow {
  /** YYYY-MM-DD */
  readonly startDate: string;
  /** HH:MM, 24-hour */
  readonly startTime: string;
  readonly granularity: FgGranularity;
  readonly filterType: FgFilterType;
  readonly thresholdC: number;
  readonly direction: FgDirection;
}

export interface AnalyticRun {
  readonly id: string;
  readonly projectId: string;
  readonly analyticType: FgAnalyticType;
  readonly thresholdC: number | null;
  readonly direction: FgDirection | null;
  readonly granularity: FgGranularity;
  readonly startDate: string;
  readonly startTime: string | null;
  readonly filterType: FgFilterType;
  /** Read from the API response, never assumed. Null if the response omitted it. */
  readonly units: FgUnits | null;
  readonly stats: FgStatsData;
  /** FortyGuard handle — the provenance anchor. Null for a fixture-backed run. */
  readonly activityId: string | null;
  readonly createdAt: string;
}

export interface Tile {
  readonly tileKey: string;
  readonly analyticRunId: string;
  /** `null` means missing. Never coerce to 0. */
  readonly value: number | null;
}

export type TileCollection = FgFeatureCollection<FgTileProperties & { readonly tile_key: string }>;

/* ═════════════════════════════════════════════════════════════════════════════
 * ENRICHMENT — land cover, exposure, attribution
 * ════════════════════════════════════════════════════════════════════════════*/
/**
 * Every field is nullable, matching the backend schema.
 *
 * The upstream datasets have real gaps — NLCD does not cover every cell and
 * elevation tiles have voids — so a non-nullable type here would force the
 * enrichment step to invent a value to satisfy it. `null` means missing; it is
 * never 0.
 */
export interface TileFeatures {
  readonly tileKey: string;
  readonly canopyPct: number | null;
  readonly imperviousPct: number | null;
  readonly buildingPct: number | null;
  readonly waterPct: number | null;
  readonly grassShrubPct: number | null;
  readonly albedoProxy: number | null;
  /** From OSM building-footprint density — NOT a true sky-view factor. */
  readonly opennessProxy: number | null;
  readonly elevationM: number | null;
  readonly localReliefM: number | null;
  readonly distToWaterM: number | null;
  readonly districtMeanC: number | null;
}

export interface AssetCounts {
  readonly busStop: number;
  readonly school: number;
  readonly park: number;
  readonly playground: number;
  readonly hospital: number;
}

/** Nullable throughout: a tile outside a census block group has no exposure. */
export interface Exposure {
  readonly tileKey: string;
  /** Dasymetric estimate — non-integer by construction, not a count. */
  readonly population: number | null;
  readonly pctOver65: number | null;
  readonly pctPoverty: number | null;
  /** Census-TRACT resolution — coarser than the tile. Label it as such. */
  readonly sviScore: number | null;
  readonly sviSourceGeoid: string | null;
  readonly assets: AssetCounts;
}

/** One SHAP driver contribution. */
export interface AttributionDriver {
  readonly feature: string;
  /** Plain-language label for display, e.g. "Missing tree canopy". */
  readonly label: string;
  /** Signed contribution in °C. */
  readonly contributionC: number;
  /** Share of the explained anomaly, 0–1. */
  readonly share: number;
}

export interface Attribution {
  readonly tileKey: string;
  readonly modelVersion: string;
  /** Anomaly vs the district mean, with its interval. */
  readonly anomaly: Estimate;
  readonly drivers: readonly AttributionDriver[];
  readonly topDriver: string;
}

/* ═════════════════════════════════════════════════════════════════════════════
 * PRIORITIZATION
 * ════════════════════════════════════════════════════════════════════════════*/
export interface TilePriority {
  readonly tileKey: string;
  readonly rank: number;
  readonly riskLevel: RiskLevel;
  /** Hours above the threshold. Null where the analytic returned no value. */
  readonly exceedanceHours: number | null;
  /** Longest continuous run of hours past the threshold. */
  readonly persistenceHours: number | null;
  /** Hour of day (0–23) of peak temperature, converted to LOCAL time. */
  readonly peakHourLocal: number | null;
  readonly population: number | null;
  /** population × exceedanceHours. A derived quantity with units, not an index. */
  readonly personHeatHours: number | null;
  /** personHeatHours × (1 + λ · SVI). λ is a policy choice. */
  readonly equityWeightedPhh: number | null;
}

/* ═════════════════════════════════════════════════════════════════════════════
 * INTERVENTIONS & PLANS
 * ════════════════════════════════════════════════════════════════════════════*/
export type InterventionUnit = 'tree' | 'm2' | 'structure' | 'linear_m' | 'station';

export interface InterventionCatalogEntry {
  readonly code: string;
  readonly category: InterventionCategory;
  readonly name: string;
  readonly unit: InterventionUnit;
  readonly unitCostUsd: number;
  /** Published effect range. Predictions are clamped to it (SRS §9.3.2). */
  readonly deltaCLow: number;
  readonly deltaCHigh: number;
  readonly lifespanYears: number;
  readonly maintenanceUsdYr: number;
  /** Required — the app refuses to start with an uncited entry. */
  readonly sourceCitation: string;
}

export type PlanObjective =
  | 'max_delta_c'
  | 'max_person_heat_hours'
  | 'equity_weighted';

export interface PlanRequest {
  readonly budgetUsd: number;
  readonly objective: PlanObjective;
  readonly equityLambda: number;
}

export interface PlanItem {
  readonly id: string;
  readonly rank: number;
  readonly tileKey: string;
  readonly interventionCode: string;
  readonly interventionName: string;
  readonly category: InterventionCategory;
  readonly quantity: number;
  readonly unit: InterventionUnit;
  readonly unitCostUsd: number;
  readonly costUsd: number;
  readonly predictedDelta: Estimate;
  readonly heatHoursAvoided: number;
  readonly personHeatHoursAvoided: number;
  readonly peopleAffected: number;
  /** Why the optimizer selected it, at selection time. */
  readonly marginalBenefitPerUsd: number;
  /** LLM-authored prose. Nullable by design — the plan is valid without it. */
  readonly rationale: string | null;
}

export interface PlanTotals {
  readonly totalCostUsd: number;
  /** Echoed so a plan is never rendered without the ceiling it respected. */
  readonly budgetUsd: number;
  /**
   * Area-weighted across the whole AOI including untreated tiles, so this is
   * NOT the mean of the item deltas and will normally be smaller.
   */
  readonly meanDelta: Estimate;
  readonly heatHoursAvoided: number;
  readonly personHeatHoursAvoided: number;
  readonly peopleReached: number;
  /** Null when exposure data is too sparse to compute it honestly. */
  readonly pctReachedTopSviQuartile: number | null;
}

export interface Plan {
  readonly id: string;
  readonly projectId: string;
  readonly budgetUsd: number;
  readonly objective: PlanObjective;
  readonly equityLambda: number;
  readonly thresholdC: number;
  readonly modelVersion: string;
  readonly totals: PlanTotals;
  readonly items: readonly PlanItem[];
  /** Required field — a client rendering a plan always has the disclaimer. */
  readonly estimateDisclaimer: string;
  readonly createdAt: string;
}

/** A candidate the optimizer considered but excluded. */
export interface InfeasibleCandidate {
  readonly tileKey: string;
  readonly interventionCode: string;
  readonly reason: string;
}

/* ═════════════════════════════════════════════════════════════════════════════
 * VERIFICATION
 * ════════════════════════════════════════════════════════════════════════════*/
export interface VerificationProtocol {
  readonly planId: string;
  readonly aoi: FgFeatureCollection;
  readonly granularity: FgGranularity;
  readonly startTime: string;
  readonly analyticType: FgAnalyticType;
  readonly scheduledFor: string;
  readonly treatedTileKeys: readonly string[];
  readonly controlTileKeys: readonly string[];
  readonly statisticalTest: 'difference_in_differences';
}

export interface VerificationResult {
  readonly treatedBaselineC: number;
  readonly treatedFollowupC: number;
  readonly controlBaselineC: number;
  readonly controlFollowupC: number;
  /** Difference of differences. */
  readonly observedDeltaC: number;
  readonly predictedDelta: Estimate;
  /**
   * Whether the observation fell inside the predicted interval. Deliberately
   * NOT named `success`: a prediction can be correct about a disappointing
   * outcome, and an observation outside the interval is information about the
   * model, not a verdict on the intervention.
   */
  readonly withinCi: boolean;
  readonly method: 'difference_in_differences';
  /** Confounder warning — displayed adjacent to the number, not in a footnote. */
  readonly caveat: string;
  readonly measuredAt: string;
}

/* ═════════════════════════════════════════════════════════════════════════════
 * JOBS & AGENT
 * ════════════════════════════════════════════════════════════════════════════*/
export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'degraded';

export type JobKind = 'diagnose' | 'plan' | 'verify' | 'harvest';

export interface Job {
  readonly id: string;
  /** Null for a harvest job, which is not scoped to a project. */
  readonly projectId: string | null;
  readonly kind: JobKind;
  readonly status: JobStatus;
  readonly stage: string | null;
  readonly progressPct: number;
  /** Derived from createdAt server-side, not stored. */
  readonly elapsedS: number;
  /**
   * The failure message when `failed`, and the degradation reason when
   * `degraded` — a successful-but-partial run explains itself here.
   */
  readonly error: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface JobProgressEvent {
  readonly jobId: string;
  readonly stage: string;
  readonly progressPct: number;
  readonly message: string;
  readonly elapsedS: number;
}

export type AgentNodeType = 'deterministic' | 'llm';

export type GuardVerdict = 'pass' | 'retried' | 'failed';

export interface AgentNodeRecord {
  readonly name: string;
  readonly type: AgentNodeType;
  readonly durationMs: number;
  readonly tokensIn: number | null;
  readonly tokensOut: number | null;
}

/**
 * One numeral the guard rejected.
 *
 * The token alone does not show whether the model invented a figure or merely
 * reformatted an allowed one, so the surrounding context is kept too — that
 * distinction is the whole diagnostic value of the trace.
 */
export interface GuardViolation {
  readonly node: string;
  readonly token: string;
  readonly context: string;
  readonly reason: string;
}

export interface AgentRun {
  readonly id: string;
  readonly planId: string;
  readonly graphVersion: string;
  readonly model: string;
  readonly nodes: readonly AgentNodeRecord[];
  readonly guardVerdict: GuardVerdict;
  /** Empty on a clean run. Populated violations are displayed, not suppressed. */
  readonly guardViolations: readonly GuardViolation[];
  readonly tokensIn: number | null;
  readonly tokensOut: number | null;
  readonly durationMs: number | null;
  readonly createdAt: string;
}

/* ═════════════════════════════════════════════════════════════════════════════
 * PROVENANCE & MODEL VALIDATION
 * ════════════════════════════════════════════════════════════════════════════*/
export type ProvenanceSourceType =
  | 'fortyguard'
  | 'derived'
  | 'model'
  | 'catalog'
  | 'external_dataset';

export interface ProvenanceRecord {
  readonly figureLabel: string;
  readonly value: string;
  readonly sourceType: ProvenanceSourceType;
  /** FortyGuard activity handle, where applicable. */
  readonly activityId: string | null;
  readonly sourceDetail: string;
  readonly retrievedAt: string;
}

export interface ModelValidation {
  readonly modelVersion: string;
  readonly trainingTileCount: number;
  readonly trainingDistricts: readonly string[];
  readonly heldOutDistricts: readonly string[];
  readonly maeC: number;
  readonly r2: number;
  /** Fraction of held-out observations inside p10–p90. Target ≈ 0.80. */
  readonly intervalCoverage: number;
  readonly features: readonly string[];
  readonly limitations: readonly string[];
}

/* ═════════════════════════════════════════════════════════════════════════════
 * SYSTEM
 * ════════════════════════════════════════════════════════════════════════════*/
export type DataMode = 'live' | 'cached' | 'fixture';

export interface CreditStatus {
  readonly remaining: number | null;
  readonly reserve: number;
  readonly submissionsToday: number;
  readonly dailyCap: number;
  readonly liveAnalysisEnabled: boolean;
}

/**
 * `skipped` is distinct from `ok`: liveness must stay cheap, so a dependency it
 * does not probe is reported as unchecked rather than as healthy.
 */
export type DependencyState = 'ok' | 'down' | 'skipped';

export interface HealthStatus {
  readonly status: 'ok' | 'degraded' | 'down';
  readonly version: string;
  readonly mode: DataMode;
  readonly modelVersion: string;
  readonly dependencies: Readonly<Record<string, DependencyState>>;
}
