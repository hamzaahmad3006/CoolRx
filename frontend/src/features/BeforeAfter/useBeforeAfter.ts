'use client';

import { USE_FIXTURES } from '@/constants';

/** Histogram resolution for the per-tile cooling distribution. */
const BIN_COUNT = 12;
import { useCallback, useMemo } from 'react';

import { useAppDispatch, useAppSelector } from '@/redux/hooks';
import { setSwipePosition } from '@/redux/slices/uiSlice';
import {
  useGetCounterfactualQuery,
  useGetPlanQuery,
  useGetTilesQuery,
} from '@/redux/api/coolRxApi';
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


interface UseBeforeAfterArgs {
  readonly planId: string | null;
}

interface UseBeforeAfterResult {
  readonly before: TileCollection | null;
  readonly after: TileCollection | null;
  readonly sharedDomain: readonly [number, number];
  /*
   * Null until the plan has loaded. Previously these were taken from the
   * fixture regardless of mode, so they were never null and never wrong-looking
   * -- they were just somebody else's numbers.
   */
  readonly meanDelta: Estimate | null;
  readonly heatHoursAvoided: number | null;
  readonly personHeatHoursAvoided: number | null;
  readonly peopleReached: number | null;
  /** Null when exposure data is too sparse to compute the quartile honestly. */
  readonly pctTopSviQuartile: number | null;
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
  const sessionPlanId = useAppSelector((state) => state.session.currentPlanId);

  // The URL wins when it names a plan; otherwise the one the Prescribe step
  // just produced.
  const resolvedPlanId = planId ?? sessionPlanId;
  const hasPlan = resolvedPlanId !== null;

  const query = useGetCounterfactualQuery(resolvedPlanId ?? '', {
    skip: USE_FIXTURES || !hasPlan,
  });

  /*
   * The plan carries the totals and names the project the before-field belongs
   * to. Both were previously taken from `PRESCRIPTION_FIXTURE` regardless of
   * mode, so a live session displayed one plan's map beside another plan's
   * heat-hours, people reached and equity share — with nothing on screen to say
   * the two halves described different things.
   */
  const planQuery = useGetPlanQuery(resolvedPlanId ?? '', {
    skip: USE_FIXTURES || !hasPlan,
  });
  const projectId = planQuery.data?.projectId;

  const beforeQuery = useGetTilesQuery(
    { projectId: projectId ?? '', analytic: 'tcm' },
    { skip: USE_FIXTURES || projectId === undefined },
  );

  const before = useMemo<TileCollection | null>(() => {
    if (USE_FIXTURES) return BEFORE_TILES;
    if (beforeQuery.data === undefined) return null;
    // The measured field the counterfactual is compared against. Without it the
    // swipe had nothing on its left-hand side.
    return {
      type: 'FeatureCollection',
      features: beforeQuery.data.features,
    };
  }, [beforeQuery.data]);

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

  const totals = USE_FIXTURES
    ? PRESCRIPTION_FIXTURE.totals
    : planQuery.data?.totals;

  /**
   * Per-tile cooling, from the two fields the swipe already shows.
   *
   * Derived rather than fetched: the histogram must describe exactly the tiles
   * on the map, and a separate endpoint computing the same differences could
   * drift from them. Tiles the model refused are absent from `after` and so are
   * absent here too, which is correct — a refused tile has no predicted delta,
   * and counting it as zero would report "no change" for ground the model
   * declined to speak about.
   */
  const deltas = useMemo<readonly number[]>(() => {
    if (USE_FIXTURES) return [];
    if (before === null || after === null) return [];
    const baseline = new Map<string, number>();
    before.features.forEach((f) => {
      const value = f.properties.value;
      if (value !== null) baseline.set(f.properties.tile_key, value);
    });
    const out: number[] = [];
    after.features.forEach((f) => {
      const post = f.properties.value;
      const pre = baseline.get(f.properties.tile_key);
      if (post !== null && pre !== undefined) out.push(post - pre);
    });
    return out;
  }, [before, after]);

  const liveBins = useMemo(() => {
    if (deltas.length === 0) return [];
    const lo = Math.min(...deltas);
    const hi = Math.max(...deltas);
    const width = (hi - lo) / BIN_COUNT || 1;
    const counts = new Array<number>(BIN_COUNT).fill(0);
    deltas.forEach((d) => {
      const index = Math.min(BIN_COUNT - 1, Math.floor((d - lo) / width));
      counts[index] = (counts[index] ?? 0) + 1;
    });
    return counts.map((count, index) => ({
      deltaC: lo + width * (index + 0.5),
      count,
    }));
  }, [deltas]);

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
    meanDelta: USE_FIXTURES ? MEAN_DELTA : (totals?.meanDelta ?? null),
    heatHoursAvoided: totals?.heatHoursAvoided ?? null,
    personHeatHoursAvoided: totals?.personHeatHoursAvoided ?? null,
    peopleReached: totals?.peopleReached ?? null,
    pctTopSviQuartile: totals?.pctReachedTopSviQuartile ?? null,
    treatedTileCount: USE_FIXTURES
      ? TREATED_TILE_COUNT
      : (planQuery.data?.items.length ?? 0),
    deltaBins: USE_FIXTURES ? deltaHistogram() : liveBins,
    maxAbsDelta: USE_FIXTURES
      ? MAX_ABS_DELTA
      : (deltas.reduce((m, d) => Math.max(m, Math.abs(d)), 0) || 1),
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
