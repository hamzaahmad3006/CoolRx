/**
 * CoolRx REST contract — request and response shapes for every endpoint in
 * SRS §17. Mirrors the backend's FastAPI/pydantic schemas.
 */

import type {
  AgentRun,
  AnalyticRun,
  CreditStatus,
  Exposure,
  HealthStatus,
  InfeasibleCandidate,
  InterventionCatalogEntry,
  Job,
  ModelValidation,
  Plan,
  PlanObjective,
  Project,
  ProvenanceRecord,
  TileCollection,
  TilePriority,
  Attribution,
  VerificationProtocol,
  VerificationResult,
} from './domain';
import type {
  FgAnalyticType,
  FgFeatureCollection,
  FgGranularity,
  FgStatsData,
} from './fortyguard';

/* ─────────────────────────────────────────────────────────────────────────────
 * Error envelope (SRS §17.2)
 * ────────────────────────────────────────────────────────────────────────────*/
export type ApiErrorCode =
  | 'AOI_AREA_EXCEEDED'
  | 'AOI_OUTSIDE_COVERAGE'
  | 'AOI_NOT_CLOSED'
  | 'AOI_INVALID_GEOMETRY'
  | 'DATE_OUT_OF_RANGE'
  | 'GRANULARITY_INVALID'
  | 'CREDITS_BELOW_RESERVE'
  | 'RATE_LIMITED'
  | 'JOB_ALREADY_RUNNING'
  | 'UPSTREAM_UNAVAILABLE'
  | 'NOT_FOUND'
  | 'UNAUTHORIZED'
  | 'VALIDATION_FAILED'
  | 'INTERNAL_ERROR';

export interface ApiErrorDetail {
  readonly code: ApiErrorCode;
  readonly message: string;
  readonly field: string | null;
  readonly details: Readonly<Record<string, string | number | boolean>>;
  readonly correlationId: string;
}

export interface ApiErrorEnvelope {
  readonly error: ApiErrorDetail;
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Projects
 * ────────────────────────────────────────────────────────────────────────────*/
export interface CreateProjectRequest {
  readonly name: string;
  readonly city: string;
  readonly state: string;
  readonly aoi: FgFeatureCollection;
}

export interface CreateProjectFromPresetRequest {
  readonly presetId: string;
}

export type CreateProjectResponse = Project;

export interface ListProjectsResponse {
  readonly presets: readonly Project[];
  readonly recent: readonly Project[];
}

/** Landing-page preset card. */
export interface PresetSummary {
  readonly presetId: string;
  readonly name: string;
  readonly city: string;
  readonly state: string;
  readonly peakTempC: number;
  readonly hoursAboveThreshold: number;
  readonly population: number;
  readonly thumbnailUrl: string;
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Diagnosis & jobs
 * ────────────────────────────────────────────────────────────────────────────*/
export interface DiagnoseRequest {
  readonly startDate: string;
  readonly startTime: string;
  readonly granularity: FgGranularity;
  readonly thresholdC: number;
  /** Build the exceedance ladder (11 threshold steps) for impact conversion. */
  readonly buildLadder: boolean;
}

export interface DiagnoseResponse {
  readonly jobId: string;
  readonly status: 'queued';
  readonly stages: readonly string[];
}

export type JobResponse = Job;

/* ─────────────────────────────────────────────────────────────────────────────
 * Tiles, stats, attribution, exposure
 * ────────────────────────────────────────────────────────────────────────────*/
export interface TilesQuery {
  readonly analytic: FgAnalyticType;
  readonly simplify: 'auto' | 'none';
}

export interface TilesResponse {
  readonly analytic: FgAnalyticType;
  /** Echoed from the API's own stats_data.units — never assumed client-side. */
  readonly units: string;
  readonly thresholdC: number | null;
  readonly granularity: FgGranularity;
  readonly tileCount: number;
  readonly generatedFrom: { readonly activityId: string };
  readonly features: TileCollection['features'];
}

export interface StatsResponse {
  readonly analyticRuns: readonly AnalyticRun[];
  readonly stats: FgStatsData;
  readonly hotspotCutoff: number;
  readonly districtMeanC: number;
}

export interface AttributionResponse {
  readonly items: readonly Attribution[];
}

export interface ExposureResponse {
  readonly items: readonly Exposure[];
}

export interface PriorityResponse {
  readonly items: readonly TilePriority[];
  readonly equityLambda: number;
}

export interface CandidatesResponse {
  readonly catalog: readonly InterventionCatalogEntry[];
  readonly infeasible: readonly InfeasibleCandidate[];
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Plans
 * ────────────────────────────────────────────────────────────────────────────*/
export interface CreatePlanRequest {
  readonly budgetUsd: number;
  readonly objective: PlanObjective;
  readonly equityLambda: number;
}

export type CreatePlanResponse = Plan;
export type GetPlanResponse = Plan;

export interface CounterfactualResponse {
  /** Predicted post-intervention field. */
  readonly features: TileCollection['features'];
  /** Shared colour-scale domain — both sides of the swipe MUST use it. */
  readonly scaleDomain: readonly [number, number];
  readonly units: string;
}

export interface ProvenanceResponse {
  readonly records: readonly ProvenanceRecord[];
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Verification
 * ────────────────────────────────────────────────────────────────────────────*/
export type VerificationProtocolResponse = VerificationProtocol;

export interface VerifyRequest {
  readonly followupDate: string;
}

export type VerifyResponse = VerificationResult;

/* ─────────────────────────────────────────────────────────────────────────────
 * System
 * ────────────────────────────────────────────────────────────────────────────*/
export type AgentTraceResponse = AgentRun;
export type ModelValidationResponse = ModelValidation;
export type CreditsResponse = CreditStatus;
export type HealthResponse = HealthStatus;

/* ─────────────────────────────────────────────────────────────────────────────
 * Route parameters
 * ────────────────────────────────────────────────────────────────────────────*/
export interface ProjectRouteParams {
  readonly projectId: string;
}

export interface PlanRouteParams {
  readonly planId: string;
}

export interface AgentRunRouteParams {
  readonly runId: string;
}
