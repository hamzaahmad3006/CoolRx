'use client';

import { USE_FIXTURES } from '@/constants';
import { useCallback, useMemo, useState } from 'react';

import type { InterventionCategory } from '@/constants';
import { PRESCRIPTION_FIXTURE } from '@/features/Prescription/prescription.fixture';
import { useGetPlanQuery, useGetProvenanceQuery } from '@/redux/api/coolRxApi';
import type { Plan, PlanItem, ProvenanceRecord } from '@/types';

import { PROVENANCE_FIXTURE } from './actionPlan.fixture';


export interface CategoryRollup {
  readonly category: InterventionCategory;
  readonly itemCount: number;
  readonly costUsd: number;
  readonly shareOfBudget: number;
}

interface UseActionPlanArgs {
  readonly planId: string;
}

interface UseActionPlanResult {
  readonly plan: Plan | null;
  readonly items: readonly PlanItem[];
  readonly provenance: readonly ProvenanceRecord[];
  readonly rollup: readonly CategoryRollup[];
  /** Items whose rationale the guard rejected, so the prose was dropped. */
  readonly itemsWithoutRationale: number;
  readonly isLoading: boolean;
  readonly errorMessage: string | null;
  readonly isPrinting: boolean;
  readonly onDownload: () => void;
}

export function useActionPlan({ planId }: UseActionPlanArgs): UseActionPlanResult {
  const planQuery = useGetPlanQuery(planId, { skip: USE_FIXTURES });
  const provenanceQuery = useGetProvenanceQuery(planId, { skip: USE_FIXTURES });
  const [isPrinting, setIsPrinting] = useState(false);

  const plan = useMemo<Plan | null>(() => {
    if (USE_FIXTURES) return { ...PRESCRIPTION_FIXTURE, id: planId };
    return planQuery.data ?? null;
  }, [planId, planQuery.data]);

  const provenance = useMemo<readonly ProvenanceRecord[]>(() => {
    if (USE_FIXTURES) return PROVENANCE_FIXTURE;
    return provenanceQuery.data?.records ?? [];
  }, [provenanceQuery.data]);

  const items = plan?.items ?? [];

  /**
   * Spend by intervention category.
   *
   * Computed from the items rather than requested separately, so the rollup and
   * the table can never disagree — a summary that contradicts the detail beneath
   * it is worse than no summary.
   */
  const rollup = useMemo<readonly CategoryRollup[]>(() => {
    const total = items.reduce((sum, item) => sum + item.costUsd, 0);
    const byCategory = new Map<InterventionCategory, { count: number; cost: number }>();

    for (const item of items) {
      const current = byCategory.get(item.category) ?? { count: 0, cost: 0 };
      byCategory.set(item.category, {
        count: current.count + 1,
        cost: current.cost + item.costUsd,
      });
    }

    return [...byCategory.entries()]
      .map(([category, value]) => ({
        category,
        itemCount: value.count,
        costUsd: value.cost,
        shareOfBudget: total > 0 ? value.cost / total : 0,
      }))
      .sort((a, b) => b.costUsd - a.costUsd);
  }, [items]);

  const itemsWithoutRationale = useMemo(
    () => items.filter((item) => item.rationale === null).length,
    [items],
  );

  /**
   * Print to PDF via the browser.
   *
   * Deliberately not a server-rendered download yet: the print stylesheet renders
   * the same DOM the reader just reviewed, so the PDF cannot disagree with the
   * page. A server-side renderer is a second code path that can drift, and the
   * report's whole claim is that every figure traces to one source.
   */
  const onDownload = useCallback((): void => {
    setIsPrinting(true);
    // Let the state change paint before the modal print dialog blocks the thread.
    window.setTimeout(() => {
      window.print();
      setIsPrinting(false);
    }, 50);
  }, []);

  return {
    plan,
    items,
    provenance,
    rollup,
    itemsWithoutRationale,
    isLoading: !USE_FIXTURES && (planQuery.isLoading || provenanceQuery.isLoading),
    errorMessage:
      !USE_FIXTURES && planQuery.isError ? 'We couldn’t load this plan.' : null,
    isPrinting,
    onDownload,
  };
}
