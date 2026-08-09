'use client';

import { useCallback, useMemo } from 'react';

import { useAppDispatch, useAppSelector } from '@/redux/hooks';
import { setSwipePosition } from '@/redux/slices/uiSlice';
import { useGetCounterfactualQuery } from '@/redux/api/coolRxApi';
import type { Estimate, TileCollection } from '@/types';
import { DIAGNOSIS_CENTER } from '@/features/Diagnosis/diagnosis.fixture';
import { PRESCRIPTION_FIXTURE } from '@/features/Prescription/prescription.fixture';
import {
  AFTER_TILES,
  BEFORE_TILES,
  MAX_ABS_DELTA,
  MEAN_DELTA,
  SHARED_DOMAIN,
  TREATED_TILE_COUNT,
  deltaHistogram,
} from './beforeAfter.fixture';

const USE_FIXTURES = process.env.NEXT_PUBLIC_USE_FIXTURES === 'true';

interface UseBeforeAfterArgs {
  readonly planId: string;
}

interface UseBeforeAfterResult {
  readonly before: TileCollection | null;
  readonly after: TileCollection | null;
  readonly sharedDomain: readonly [number, number];
  readonly meanDelta: Estimate;
  readonly heatHoursAvoided: number;
  readonly personHeatHoursAvoided: number;
  readonly peopleReached: number;
  readonly pctTopSviQuartile: number;
  readonly treatedTileCount: number;
  readonly deltaBins: readonly { deltaC: number; count: number }[];
  readonly maxAbsDelta: number;
  readonly center: readonly [number, number];
  readonly swipePosition: number;
  readonly isLoading: boolean;
  readonly errorMessage: string | null;
  readonly estimateDisclaimer: string;
  readonly onSwipeChange: (position: number) => void;
}

export function useBeforeAfter({
  planId,
}: UseBeforeAfterArgs): UseBeforeAfterResult {
  const dispatch = useAppDispatch();
  const swipePosition = useAppSelector((state) => state.ui.swipePosition);

  const query = useGetCounterfactualQuery(planId, { skip: USE_FIXTURES });

  const before = useMemo<TileCollection | null>(
    () => (USE_FIXTURES ? BEFORE_TILES : null),
    [],
  );

  const after = useMemo<TileCollection | null>(() => {
    if (USE_FIXTURES) return AFTER_TILES;
    if (query.data === undefined) return null;
    return { type: 'FeatureCollection', features: query.data.features };
  }, [query.data]);

  /**
   * One domain for both sides. When live, it comes from the backend so the server
   * — not the client — owns the guarantee that the two fields share a scale.
   */
  const sharedDomain = useMemo<readonly [number, number]>(() => {
    if (USE_FIXTURES) return SHARED_DOMAIN;
    return query.data?.scaleDomain ?? [0, 1];
  }, [query.data]);

  const totals = PRESCRIPTION_FIXTURE.totals;

  const onSwipeChange = useCallback(
    (position: number): void => {
      dispatch(setSwipePosition(position));
    },
    [dispatch],
  );

  return {
    before,
    after,
    sharedDomain,
    meanDelta: USE_FIXTURES ? MEAN_DELTA : totals.meanDelta,
    heatHoursAvoided: totals.heatHoursAvoided,
    personHeatHoursAvoided: totals.personHeatHoursAvoided,
    peopleReached: totals.peopleReached,
    pctTopSviQuartile: totals.pctReachedTopSviQuartile,
    treatedTileCount: USE_FIXTURES ? TREATED_TILE_COUNT : 0,
    deltaBins: USE_FIXTURES ? deltaHistogram() : [],
    maxAbsDelta: USE_FIXTURES ? MAX_ABS_DELTA : 1,
    center: DIAGNOSIS_CENTER,
    swipePosition,
    isLoading: query.isLoading,
    errorMessage: query.isError
      ? 'We couldn’t load the predicted field for this plan.'
      : null,
    estimateDisclaimer: PRESCRIPTION_FIXTURE.estimateDisclaimer,
    onSwipeChange,
  };
}
