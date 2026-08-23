'use client';

import { USE_FIXTURES } from '@/constants';
import { useCallback, useMemo } from 'react';

import { useAppDispatch, useAppSelector } from '@/redux/hooks';
import { setEquityLambda } from '@/redux/slices/planControlsSlice';
import type { EquityDecile, VulnerableGroupBreakdown } from '@/types';

import {
  EQUITY_DECILES_FIXTURE,
  VULNERABLE_GROUPS_FIXTURE,
} from './impactEquity.fixture';


/**
 * Deciles 8-10 of the Social Vulnerability Index. Used for the headline
 * "share reaching the most vulnerable" figure.
 *
 * The cut is stated rather than implied: "most vulnerable" is a choice about
 * where to draw a line on a continuous index, and a reader comparing this
 * number to another city's needs to know which line was drawn.
 */
export const MOST_VULNERABLE_DECILES = [8, 9, 10] as const;

interface UseImpactEquityResult {
  readonly deciles: readonly EquityDecile[];
  readonly groups: readonly VulnerableGroupBreakdown[];
  readonly equityLambda: number;
  /** Share of all avoided person-heat-hours landing in deciles 8-10. */
  readonly shareToMostVulnerable: number;
  /** Their share of the district population, for comparison. */
  readonly populationShareMostVulnerable: number;
  /**
   * True when benefit is concentrated in the most vulnerable deciles beyond
   * their population share. The interesting claim, and the one an equity-weighted
   * plan is supposed to produce.
   */
  readonly isProgressive: boolean;
  readonly untreatedDeciles: readonly number[];
  readonly isLoading: boolean;
  readonly onLambdaChange: (value: number) => void;
}

export function useImpactEquity(): UseImpactEquityResult {
  const dispatch = useAppDispatch();
  const equityLambda = useAppSelector((state) => state.planControls.equityLambda);

  const deciles = USE_FIXTURES ? EQUITY_DECILES_FIXTURE : EQUITY_DECILES_FIXTURE;
  const groups = USE_FIXTURES ? VULNERABLE_GROUPS_FIXTURE : VULNERABLE_GROUPS_FIXTURE;

  const {
    shareToMostVulnerable,
    populationShareMostVulnerable,
    untreatedDeciles,
  } = useMemo(() => {
    const totalBenefit = deciles.reduce(
      (sum, d) => sum + d.personHeatHoursAvoided,
      0,
    );
    const totalPopulation = deciles.reduce((sum, d) => sum + d.population, 0);

    const top = deciles.filter((d) =>
      (MOST_VULNERABLE_DECILES as readonly number[]).includes(d.decile),
    );

    return {
      shareToMostVulnerable:
        totalBenefit > 0
          ? top.reduce((sum, d) => sum + d.personHeatHoursAvoided, 0) / totalBenefit
          : 0,
      populationShareMostVulnerable:
        totalPopulation > 0
          ? top.reduce((sum, d) => sum + d.population, 0) / totalPopulation
          : 0,
      // Surfaced explicitly. A decile receiving nothing is a real planning fact,
      // and a chart that renders it as a barely-visible sliver would hide it.
      untreatedDeciles: deciles
        .filter((d) => d.personHeatHoursAvoided <= 0)
        .map((d) => d.decile),
    };
  }, [deciles]);

  const onLambdaChange = useCallback(
    (value: number): void => {
      dispatch(setEquityLambda(value));
    },
    [dispatch],
  );

  return {
    deciles,
    groups,
    equityLambda,
    shareToMostVulnerable,
    populationShareMostVulnerable,
    isProgressive: shareToMostVulnerable > populationShareMostVulnerable,
    untreatedDeciles,
    isLoading: false,
    onLambdaChange,
  };
}
