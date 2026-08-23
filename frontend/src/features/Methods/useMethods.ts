'use client';

import { useMemo } from 'react';

import { useGetModelValidationQuery } from '@/redux/api/coolRxApi';
import type { ModelValidation } from '@/types';

import { MODEL_VALIDATION_FIXTURE } from '@/features/AgentTrace/agentTrace.fixture';

const USE_FIXTURES = process.env.NEXT_PUBLIC_USE_FIXTURES !== 'false';

/**
 * A calibrated p10–p90 interval should contain about 80% of held-out
 * observations. Materially below that means the published intervals are too
 * narrow and every figure on the site is overconfident by the same margin.
 */
export const COVERAGE_TARGET = 0.8;

/** How far below target is tolerable before the page says the ranges are optimistic. */
const COVERAGE_TOLERANCE = 0.05;

interface UseMethodsResult {
  readonly validation: ModelValidation | null;
  readonly isLoading: boolean;
  readonly coverageIsHealthy: boolean;
  /**
   * Which side of target the coverage sits on.
   *
   * `coverageIsHealthy` alone cannot say. A band that is too narrow is
   * overconfident and dangerous; one that is too wide is merely cautious, and
   * describing the second as "well-calibrated" would be a false reassurance
   * printed directly beneath the number that contradicts it.
   */
  readonly coverageState: 'calibrated' | 'conservative' | 'overconfident';
  readonly coverageTarget: number;
}

export function useMethods(): UseMethodsResult {
  const query = useGetModelValidationQuery(undefined, { skip: USE_FIXTURES });

  /*
   * No silent fixture fallback on the live path.
   *
   * Falling back to `MODEL_VALIDATION_FIXTURE` when the request fails would
   * print one model's metrics under another model's version string, on the page
   * whose entire purpose is to say what this model can and cannot do. If the
   * endpoint is unavailable the page must say so.
   */
  const validation = useMemo<ModelValidation | null>(
    () => (USE_FIXTURES ? MODEL_VALIDATION_FIXTURE : (query.data ?? null)),
    [query.data],
  );

  return {
    validation,
    isLoading: !USE_FIXTURES && query.isLoading,
    // Only the lower side matters. Coverage well *above* target means the
    // intervals are conservative, which is a defensible choice rather than a
    // defect, so it is not flagged.
    coverageIsHealthy:
      validation !== null &&
      validation.intervalCoverage >= COVERAGE_TARGET - COVERAGE_TOLERANCE,
    coverageState:
      validation === null
        ? 'calibrated'
        : validation.intervalCoverage < COVERAGE_TARGET - COVERAGE_TOLERANCE
          ? 'overconfident'
          : validation.intervalCoverage > COVERAGE_TARGET + COVERAGE_TOLERANCE
            ? 'conservative'
            : 'calibrated',
    coverageTarget: COVERAGE_TARGET,
  };
}
