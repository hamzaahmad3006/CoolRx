'use client';

import { useRouter } from 'next/navigation';
import { useCallback } from 'react';

import { useAppDispatch } from '@/redux/hooks';
import { setCurrentProject } from '@/redux/slices/sessionSlice';
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
  readonly peakTempC: number;
  readonly hoursAboveThreshold: number;
  readonly population: number;
}

export interface WorkflowStep {
  readonly label: string;
  readonly caption: string;
  readonly icon: IconName;
}

/**
 * The three pre-baked demo districts. These are static by design: their
 * FortyGuard responses are cached and committed as fixtures so the demo loads in
 * under three seconds and costs zero API credits (SRS FR-022).
 */
const PRESET_DISTRICTS: readonly PresetDistrict[] = [
  {
    presetId: 'phoenix-encanto',
    name: 'Encanto',
    city: 'Phoenix',
    state: 'AZ',
    peakTempC: 44.1,
    hoursAboveThreshold: 9,
    population: 12_400,
  },
  {
    presetId: 'la-westlake',
    name: 'Westlake',
    city: 'Los Angeles',
    state: 'CA',
    peakTempC: 38.2,
    hoursAboveThreshold: 5,
    population: 45_100,
  },
  {
    presetId: 'houston-gulfton',
    name: 'Gulfton',
    city: 'Houston',
    state: 'TX',
    peakTempC: 40.5,
    hoursAboveThreshold: 7,
    population: 28_900,
  },
] as const;

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
  readonly workflow: readonly WorkflowStep[];
  readonly openDistrict: (presetId: string) => void;
  readonly openMethods: () => void;
}

export function useLanding(): UseLandingResult {
  const router = useRouter();
  const dispatch = useAppDispatch();

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

  return {
    presets: PRESET_DISTRICTS,
    workflow: WORKFLOW_STEPS,
    openDistrict,
    openMethods,
  };
}
