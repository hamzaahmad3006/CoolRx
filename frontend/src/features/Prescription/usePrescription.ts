'use client';

import { useCallback, useEffect, useMemo } from 'react';

import { INTERVENTION_COLORS, type InterventionCategory } from '@/constants';
import { useAppDispatch, useAppSelector } from '@/redux/hooks';
import {
  setBudgetUsd,
  setEquityLambda,
  setObjective,
} from '@/redux/slices/planControlsSlice';
import { setCurrentPlan } from '@/redux/slices/sessionSlice';
import { useCreatePlanMutation, useGetPlanQuery } from '@/redux/api/coolRxApi';
import type { Plan, PlanObjective } from '@/types';
import type { SegmentOption } from '@/components/ui/SegmentedControl';
import { PRESCRIPTION_FIXTURE } from './prescription.fixture';

/**
 * Prescription screen logic: plan controls, optimisation trigger, derived
 * display values. The page component holds none of this.
 *
 * Data source follows the backend's own contract — RTK Query when the API is
 * reachable, the committed fixture when running in fixture mode (SRS FR-022).
 */

const USE_FIXTURES = process.env.NEXT_PUBLIC_USE_FIXTURES === 'true';

export const OBJECTIVE_OPTIONS: readonly SegmentOption<PlanObjective>[] = [
  {
    value: 'max_delta_c',
    label: 'Max cooling',
    title: 'Maximise mean temperature reduction across the district',
  },
  {
    value: 'max_person_heat_hours',
    label: 'Max people-hours',
    title: 'Maximise dangerous exposure-hours avoided',
  },
  {
    value: 'equity_weighted',
    label: 'Equity weighted',
    title: 'Weight exposure-hours by social vulnerability',
  },
];

export interface CategoryLegendEntry {
  readonly category: InterventionCategory;
  readonly label: string;
  readonly color: string;
}

export const CATEGORY_LEGEND: readonly CategoryLegendEntry[] = [
  { category: 'water', label: 'Water', color: INTERVENTION_COLORS.water },
  { category: 'green', label: 'Green', color: INTERVENTION_COLORS.green },
  { category: 'shade', label: 'Shade', color: INTERVENTION_COLORS.shade },
  { category: 'material', label: 'Material', color: INTERVENTION_COLORS.material },
];

interface UsePrescriptionArgs {
  readonly projectId: string;
  readonly planId: string | null;
}

interface UsePrescriptionResult {
  readonly plan: Plan | null;
  readonly isLoading: boolean;
  readonly isOptimizing: boolean;
  readonly errorMessage: string | null;
  readonly budgetUsd: number;
  readonly objective: PlanObjective;
  readonly equityLambda: number;
  readonly budgetUsedFraction: number;
  readonly onBudgetChange: (value: number) => void;
  readonly onObjectiveChange: (value: PlanObjective) => void;
  readonly onEquityLambdaChange: (value: number) => void;
  readonly onOptimize: () => void;
}

export function usePrescription({
  projectId,
  planId,
}: UsePrescriptionArgs): UsePrescriptionResult {
  const dispatch = useAppDispatch();
  const { budgetUsd, objective, equityLambda } = useAppSelector(
    (state) => state.planControls,
  );
  const currentPlanId = useAppSelector((state) => state.session.currentPlanId);

  const [createPlan, createState] = useCreatePlanMutation();

  // Skip the query entirely in fixture mode or before a plan exists.
  const planQuery = useGetPlanQuery(planId ?? '', {
    skip: USE_FIXTURES || planId === null,
  });

  const plan: Plan | null = useMemo(() => {
    if (USE_FIXTURES) return PRESCRIPTION_FIXTURE;
    if (createState.data !== undefined) return createState.data;
    if (planQuery.data !== undefined) return planQuery.data;
    return null;
  }, [createState.data, planQuery.data]);

  /**
   * Publish the plan id to session state.
   *
   * The rail's Action Plan, Verify and Agent Trace entries are plan-scoped and
   * stay disabled until this is set — without it they would never unlock, and the
   * report would be reachable only by typing its URL.
   */
  useEffect(() => {
    if (plan !== null && plan.id !== currentPlanId) {
      dispatch(setCurrentPlan(plan.id));
    }
  }, [plan, currentPlanId, dispatch]);

  const budgetUsedFraction = useMemo(() => {
    if (plan === null || plan.budgetUsd === 0) return 0;
    return Math.min(1, plan.totals.totalCostUsd / plan.budgetUsd);
  }, [plan]);

  const onOptimize = useCallback((): void => {
    if (USE_FIXTURES) return;
    void createPlan({
      projectId,
      body: { budgetUsd, objective, equityLambda },
    });
  }, [createPlan, projectId, budgetUsd, objective, equityLambda]);

  const onBudgetChange = useCallback(
    (value: number): void => {
      dispatch(setBudgetUsd(value));
    },
    [dispatch],
  );

  const onObjectiveChange = useCallback(
    (value: PlanObjective): void => {
      dispatch(setObjective(value));
    },
    [dispatch],
  );

  const onEquityLambdaChange = useCallback(
    (value: number): void => {
      dispatch(setEquityLambda(value));
    },
    [dispatch],
  );

  const errorMessage =
    createState.isError || planQuery.isError
      ? 'We couldn’t generate a plan. The analysis service may be unavailable.'
      : null;

  return {
    plan,
    isLoading: planQuery.isLoading,
    isOptimizing: createState.isLoading,
    errorMessage,
    budgetUsd,
    objective,
    equityLambda,
    budgetUsedFraction,
    onBudgetChange,
    onObjectiveChange,
    onEquityLambdaChange,
    onOptimize,
  };
}
