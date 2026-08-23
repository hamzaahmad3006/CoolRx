'use client';

import { useRouter } from 'next/navigation';
import { useCallback } from 'react';

import { useAppDispatch } from '@/redux/hooks';
import { setCurrentProject } from '@/redux/slices/sessionSlice';
import { useListProjectsQuery } from '@/redux/api/coolRxApi';
import type { IconName } from '@/constants';

/**
 * Landing page logic.
 *
 * The page component holds no state, no data access and no navigation — all of
 * it lives here, per the project architecture convention.
 */

export interface PresetDistrict {
  readonly presetId: string;
  readonly name: string;
  readonly city: string;
  readonly state: string;
  readonly areaSqMi: number;
}

export interface WorkflowStep {
  readonly label: string;
  readonly caption: string;
  readonly icon: IconName;
}

const WORKFLOW_STEPS: readonly WorkflowStep[] = [
  {
    label: 'Measure',
    caption: 'Street-level temperature at 60–100 m resolution.',
    icon: 'measure',
  },
  {
    label: 'Diagnose',
    caption: 'Which blocks are dangerously hot, and for how long.',
    icon: 'diagnose',
  },
  {
    label: 'Prescribe',
    caption: 'What to build, ranked by cooling per dollar.',
    icon: 'prescribe',
  },
  {
    label: 'Verify',
    caption: 'A pre-registered plan to re-measure the result.',
    icon: 'verified',
  },
] as const;

interface UseLandingResult {
  readonly presets: readonly PresetDistrict[];
  readonly isLoading: boolean;
  readonly error: string | null;
  readonly workflow: readonly WorkflowStep[];
  readonly openDistrict: (presetId: string) => void;
  readonly openMethods: () => void;
  readonly openStudio: () => void;
}

export function useLanding(): UseLandingResult {
  const router = useRouter();
  const dispatch = useAppDispatch();

  /*
   * Presets come from the backend, not from a constant here.
   *
   * They used to be three hard-coded districts — `phoenix-encanto`,
   * `la-westlake`, `houston-gulfton` — carrying invented statistics: 44.1 °C,
   * 12,400 people. No fixture backed them and no measurement produced them, and
   * clicking one asked the API for a project id it had never issued, which is
   * where the 422s came from.
   *
   * The card now shows only what is known before a diagnosis has run: the
   * district and its area. Peak temperature, hours above threshold and
   * population are outputs of the pipeline, and showing them here would mean
   * inventing them again.
   */
  const { data, isLoading, error } = useListProjectsQuery();

  const presets: readonly PresetDistrict[] = (data?.presets ?? []).map(
    (project) => ({
      presetId: project.id,
      name: project.name,
      city: project.city,
      state: project.state,
      areaSqMi: project.areaSqMi,
    }),
  );

  const openDistrict = useCallback(
    (presetId: string): void => {
      dispatch(setCurrentProject(presetId));
      router.push(`/p/${presetId}/diagnose`);
    },
    [dispatch, router],
  );

  const openMethods = useCallback((): void => {
    router.push('/methods');
  }, [router]);

  const openStudio = useCallback((): void => {
    router.push('/studio');
  }, [router]);

  return {
    presets,
    isLoading,
    error: error === undefined ? null : 'Districts could not be loaded.',
    workflow: WORKFLOW_STEPS,
    openDistrict,
    openMethods,
    openStudio,
  };
}
