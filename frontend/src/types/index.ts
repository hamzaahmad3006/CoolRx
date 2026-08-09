/**
 * CoolRx type definitions — barrel export.
 *
 *   import type { Plan, Estimate, TilesResponse } from '@/types';
 *
 * Strict TypeScript is a project rule: no `any`, no `unknown` anywhere in the
 * codebase without an unavoidable technical reason documented at the site.
 */

export type * from './fortyguard';
export type * from './domain';
export type * from './api';
export type * from './redux';

// Runtime value (not a type) — re-exported explicitly.
export { FG_LEGACY_MISSING } from './fortyguard';
