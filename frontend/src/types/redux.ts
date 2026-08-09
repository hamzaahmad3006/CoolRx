/**
 * Redux state shapes.
 *
 * Division of responsibility (SRS §15.3 + ADR reconciliation):
 *  - SERVER data lives in RTK Query (`redux/api`) — caching, dedup, invalidation
 *    and job polling come from the library rather than hand-rolled thunks.
 *  - Redux SLICES hold only ephemeral client state that must survive navigation.
 *  - Plan controls (budget, objective, λ) additionally mirror into URL search
 *    params so a plan configuration is shareable and reload-safe.
 */

import type { DataMode, PlanObjective } from './domain';
import type { FgAnalyticType, FgGranularity } from './fortyguard';

/* ─────────────────────────────────────────────────────────────────────────────
 * UI slice — presentation state
 * ────────────────────────────────────────────────────────────────────────────*/
export type ThemeMode = 'light' | 'dark';

export interface UiState {
  theme: ThemeMode;
  railCollapsed: boolean;
  rightPanelOpen: boolean;
  /** Tile whose attribution drawer is open, or null. */
  selectedTileKey: string | null;
  attributionDrawerOpen: boolean;
  /** Which analytic layer the map is showing. */
  activeAnalytic: FgAnalyticType;
  /** Swipe divider position on Before/After, 0–1. */
  swipePosition: number;
  degradedBannerDismissed: boolean;
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Session slice — the current working context
 * ────────────────────────────────────────────────────────────────────────────*/
export interface SessionState {
  currentProjectId: string | null;
  currentPlanId: string | null;
  dataMode: DataMode;
  /** Measurement window currently applied to the project. */
  startDate: string;
  startTime: string;
  granularity: FgGranularity;
  thresholdC: number;
  /** Active job, if any. */
  activeJobId: string | null;
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Plan-controls slice — mirrored to URL search params
 * ────────────────────────────────────────────────────────────────────────────*/
export interface PlanControlsState {
  budgetUsd: number;
  objective: PlanObjective;
  /** Equity weight. A policy choice, surfaced and labelled as one. */
  equityLambda: number;
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Root
 *
 * Note: slice state is intentionally mutable (not `readonly`) because Redux
 * Toolkit reducers mutate an Immer draft. The authoritative `RootState` type is
 * inferred from the configured store in `redux/store.ts`; this interface
 * documents the shape and is asserted against the store there.
 * ────────────────────────────────────────────────────────────────────────────*/
export interface RootStateShape {
  ui: UiState;
  session: SessionState;
  planControls: PlanControlsState;
}
