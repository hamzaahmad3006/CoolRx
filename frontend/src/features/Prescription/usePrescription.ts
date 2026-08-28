'use client';

import { useCallback, useEffect, useMemo } from 'react';

import { INTERVENTION_COLORS, type InterventionCategory, USE_FIXTURES } from '@/constants';
import { useAppDispatch, useAppSelector } from '@/redux/hooks';
import {
  setBudgetUsd,
  setEquityLambda,
  setObjective,
} from '@/redux/slices/planControlsSlice';
import { setCurrentPlan } from '@/redux/slices/sessionSlice';
import {
  useCreatePlanMutation,
  useGetJobQuery,
  useGetPlanQuery,
  useListPlansQuery,
} from '@/redux/api/coolRxApi';
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

  /*
   * Optimising is a background job, not a synchronous call.
   *
   * The POST answers 202 with a job envelope. The response type said `Plan`, so
   * the client believed the optimiser had returned a finished plan and never
   * looked again -- the page sat on "No plan yet" while the worker completed the
   * job perfectly and wrote the plan to the database.
   *
   * So: poll the job, and when it reaches a terminal state read the project's
   * plans and take the newest. `degraded` counts as finished — a plan whose
   * narration failed still has every number in it, and refusing to show it would
   * withhold a complete result because its prose is missing.
   */
  const jobId = createState.data?.jobId ?? null;
  const jobQuery = useGetJobQuery(jobId ?? '', {
    skip: USE_FIXTURES || jobId === null,
    pollingInterval: 1500,
  });
  const jobStatus = jobQuery.data?.status ?? null;
  // `degraded` is a terminal state alongside `completed`, not a flag on it: a
  // plan whose narration failed still carries every number, and withholding it
  // would hide a complete result because its prose is missing.
  const jobHasPlan = jobStatus === 'completed' || jobStatus === 'degraded';
  // There are three terminal states, not two. `failed` leaves no plan behind,
  // but it is every bit as final -- and treating it as unfinished left the
  // button reading "Optimising…" for as long as the page stayed open, on a job
  // that had already stopped seconds earlier with its reason recorded.
  const jobSettled = jobHasPlan || jobStatus === 'failed';

  const plansQuery = useListPlansQuery(projectId, {
    skip: USE_FIXTURES || !jobHasPlan,
  });

  const plan: Plan | null = useMemo(() => {
    if (USE_FIXTURES) return PRESCRIPTION_FIXTURE;
    if (planQuery.data !== undefined) return planQuery.data;
    const plans = plansQuery.data?.plans;
    if (plans !== undefined && plans.length > 0) return plans[0] ?? null;
    return null;
  }, [planQuery.data, plansQuery.data]);

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

  // The worker's own sentence, in preference to a generic notice. "No
  // intervention is both feasible and beneficial on any block in this area"
  // tells a planner something true about their district -- that nothing here
  // crosses the threshold -- where "the service may be unavailable" would send
  // them to look for a fault that does not exist.
  const jobError = jobStatus === 'failed' ? (jobQuery.data?.error ?? null) : null;
  const errorMessage =
    jobError ??
    (createState.isError || planQuery.isError
      ? 'We couldn’t generate a plan. The analysis service may be unavailable.'
      : null);

  return {
    plan,
    isLoading: planQuery.isLoading,
    // The button must stay busy for the whole job, not just the POST.
    // Reporting it done when the request returned would let a second click
    // queue a duplicate optimisation of the same project.
    isOptimizing:
      createState.isLoading || (jobId !== null && !jobSettled),
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
