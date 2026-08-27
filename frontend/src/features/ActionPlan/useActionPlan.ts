'use client';

import { API_BASE_URL, USE_FIXTURES } from '@/constants';
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
  /** Print the reviewed page itself. */
  readonly onPrint: () => void;
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

  // Memoised for the fallback's sake, not the property read. `?? []` builds a
  // fresh array on every render whenever `plan` is null, and `items` is a
  // dependency of both memos below -- so while a plan is loading, or absent, the
  // rollup and the rationale count were recomputed on every single render and
  // the memoisation around them did nothing.
  const items = useMemo<readonly PlanItem[]>(() => plan?.items ?? [], [plan]);

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
   * Two ways out, because they are different artefacts.
   *
   * `onPrint` renders the same DOM the reader just reviewed, so what comes out
   * cannot disagree with what was on screen. That is a real property and it is
   * why this path stays.
   *
   * `onDownload` asks the backend to build the report from stored values. It is
   * a second code path, which is a cost — but it is the only one that can
   * *refuse*: `report/pdf.py` will not emit a document whose headline figures
   * lack provenance, and a print stylesheet has no way to enforce that. It also
   * produces a byte-identical file every time, where a print depends on the
   * reader's browser, zoom and background-graphics setting.
   */
  const onPrint = useCallback((): void => {
    setIsPrinting(true);
    // Let the state change paint before the modal print dialog blocks the thread.
    window.setTimeout(() => {
      window.print();
      setIsPrinting(false);
    }, 50);
  }, []);

  const onDownload = useCallback((): void => {
    // A new tab rather than a hidden anchor: the reader sees the report render
    // and can decide whether to keep it, which is how a document meant to be
    // forwarded should behave.
    window.open(
      `${API_BASE_URL}/api/plans/${planId}/report.pdf`,
      '_blank',
      'noopener,noreferrer',
    );
  }, [planId]);

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
    onPrint,
  };
}
