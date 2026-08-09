'use client';

import { useCallback, useMemo } from 'react';

import type { IconName } from '@/constants';
import { useAppDispatch, useAppSelector } from '@/redux/hooks';
import { selectTile, setActiveAnalytic } from '@/redux/slices/uiSlice';
import { useGetStatsQuery, useGetTilesQuery } from '@/redux/api/coolRxApi';
import type {
  EstimateUnit,
  FgAnalyticType,
  FgStatsData,
  TileCollection,
  TilePriority,
} from '@/types';
import type { SegmentOption } from '@/components/ui/SegmentedControl';
import {
  DIAGNOSIS_CENTER,
  FIXTURE_THRESHOLD_C,
  FIXTURE_TILE_COUNT,
  fixtureDomain,
  fixturePeakHourHistogram,
  fixturePriorities,
  fixtureStats,
  fixtureTiles,
} from './diagnosis.fixture';

const USE_FIXTURES = process.env.NEXT_PUBLIC_USE_FIXTURES === 'true';

/**
 * Metadata per analytic layer. Units are declared here and echoed from the API
 * response at runtime — an hour-valued analytic must never be labelled °C
 * (SRS FR-005, FR-007).
 */
export interface AnalyticMeta {
  readonly analytic: FgAnalyticType;
  readonly label: string;
  readonly legendTitle: string;
  readonly unit: EstimateUnit;
  readonly unitLabel: string;
  readonly icon: IconName;
  readonly explanation: string;
}

export const ANALYTIC_META: Readonly<Record<FgAnalyticType, AnalyticMeta>> = {
  tcm: {
    analytic: 'tcm',
    label: 'Temperature',
    legendTitle: 'Temperature at 2 m',
    unit: 'celsius',
    unitLabel: '°C',
    icon: 'temperature',
    explanation:
      'Air temperature at head height, the level people actually experience.',
  },
  exceedance: {
    analytic: 'exceedance',
    label: 'Hours above threshold',
    legendTitle: `Hours above ${FIXTURE_THRESHOLD_C} °C`,
    unit: 'hour',
    unitLabel: 'hours',
    icon: 'exceedance',
    explanation:
      'Heat dose. Peak temperature makes headlines; duration is what harms people.',
  },
  persistence: {
    analytic: 'persistence',
    label: 'Longest continuous stretch',
    legendTitle: `Longest unbroken run above ${FIXTURE_THRESHOLD_C} °C`,
    unit: 'hour',
    unitLabel: 'hours',
    icon: 'persistence',
    explanation:
      'Continuous exposure matters more than a brief peak — there is no chance to recover.',
  },
  time_of_measure: {
    analytic: 'time_of_measure',
    label: 'Peak hour',
    legendTitle: 'Hour of peak temperature (local)',
    unit: 'count',
    unitLabel: 'hour of day',
    icon: 'peakHour',
    explanation:
      'When each block tops out. This determines where shade has to go.',
  },
};

export const ANALYTIC_OPTIONS: readonly SegmentOption<FgAnalyticType>[] = [
  { value: 'tcm', label: 'Temperature', title: ANALYTIC_META.tcm.explanation },
  {
    value: 'exceedance',
    label: 'Heat dose',
    title: ANALYTIC_META.exceedance.explanation,
  },
  {
    value: 'persistence',
    label: 'Persistence',
    title: ANALYTIC_META.persistence.explanation,
  },
  {
    value: 'time_of_measure',
    label: 'Peak hour',
    title: ANALYTIC_META.time_of_measure.explanation,
  },
];

interface UseDiagnosisArgs {
  readonly projectId: string;
}

interface UseDiagnosisResult {
  readonly activeAnalytic: FgAnalyticType;
  readonly meta: AnalyticMeta;
  readonly tiles: TileCollection | null;
  readonly domain: readonly [number, number];
  readonly stats: FgStatsData | null;
  readonly priorities: readonly TilePriority[];
  readonly peakHourHistogram: readonly number[];
  readonly districtPeakHourLocal: number;
  readonly tileCount: number;
  readonly thresholdC: number;
  readonly center: readonly [number, number];
  readonly selectedTileKey: string | null;
  readonly isLoading: boolean;
  readonly errorMessage: string | null;
  readonly distributionPoints: readonly { temperature: number; density: number }[];
  readonly onAnalyticChange: (analytic: FgAnalyticType) => void;
  readonly onSelectTile: (tileKey: string) => void;
}

export function useDiagnosis({
  projectId,
}: UseDiagnosisArgs): UseDiagnosisResult {
  const dispatch = useAppDispatch();
  const activeAnalytic = useAppSelector((state) => state.ui.activeAnalytic);
  const selectedTileKey = useAppSelector((state) => state.ui.selectedTileKey);
  const thresholdC = useAppSelector((state) => state.session.thresholdC);

  const tilesQuery = useGetTilesQuery(
    { projectId, analytic: activeAnalytic },
    { skip: USE_FIXTURES },
  );
  const statsQuery = useGetStatsQuery(projectId, { skip: USE_FIXTURES });

  const tiles = useMemo<TileCollection | null>(() => {
    if (USE_FIXTURES) return fixtureTiles(activeAnalytic);
    if (tilesQuery.data === undefined) return null;
    return {
      type: 'FeatureCollection',
      features: tilesQuery.data.features,
    };
  }, [activeAnalytic, tilesQuery.data]);

  const domain = useMemo<readonly [number, number]>(
    () => (USE_FIXTURES ? fixtureDomain(activeAnalytic) : [0, 1]),
    [activeAnalytic],
  );

  const stats = useMemo<FgStatsData | null>(() => {
    if (USE_FIXTURES) return fixtureStats(activeAnalytic);
    return statsQuery.data?.stats ?? null;
  }, [activeAnalytic, statsQuery.data]);

  const priorities = useMemo(
    () => (USE_FIXTURES ? fixturePriorities(12) : []),
    [],
  );

  const peakHourHistogram = useMemo(
    () => (USE_FIXTURES ? fixturePeakHourHistogram() : []),
    [],
  );

  /** Modal peak hour across the district. */
  const districtPeakHourLocal = useMemo(() => {
    let best = 0;
    let bestCount = -1;
    peakHourHistogram.forEach((count, hour) => {
      if (count > bestCount) {
        bestCount = count;
        best = hour;
      }
    });
    return best;
  }, [peakHourHistogram]);

  const distributionPoints = useMemo(() => {
    if (stats === null) return [];
    const { x_axis: xs, y_axis: ys } = stats.Normal_temperature_distribution;
    return xs.map((temperature, index) => ({
      temperature,
      density: ys[index] ?? 0,
    }));
  }, [stats]);

  const onAnalyticChange = useCallback(
    (analytic: FgAnalyticType): void => {
      dispatch(setActiveAnalytic(analytic));
    },
    [dispatch],
  );

  const onSelectTile = useCallback(
    (tileKey: string): void => {
      dispatch(selectTile(tileKey));
    },
    [dispatch],
  );

  const errorMessage =
    tilesQuery.isError || statsQuery.isError
      ? 'We couldn’t reach the temperature service.'
      : null;

  return {
    activeAnalytic,
    meta: ANALYTIC_META[activeAnalytic],
    tiles,
    domain,
    stats,
    priorities,
    peakHourHistogram,
    districtPeakHourLocal,
    tileCount: USE_FIXTURES ? FIXTURE_TILE_COUNT : (tilesQuery.data?.tileCount ?? 0),
    thresholdC: USE_FIXTURES ? FIXTURE_THRESHOLD_C : thresholdC,
    center: DIAGNOSIS_CENTER,
    selectedTileKey,
    isLoading: tilesQuery.isLoading || statsQuery.isLoading,
    errorMessage,
    distributionPoints,
    onAnalyticChange,
    onSelectTile,
  };
}
