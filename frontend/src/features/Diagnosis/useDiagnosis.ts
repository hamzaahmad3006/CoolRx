'use client';

import { USE_FIXTURES } from '@/constants';
import { useCallback, useMemo } from 'react';

import type { IconName } from '@/constants';
import { useAppDispatch, useAppSelector } from '@/redux/hooks';
import { selectTile, setActiveAnalytic } from '@/redux/slices/uiSlice';
import {
  useGetPrioritiesQuery,
  useGetStatsQuery,
  useGetTilesQuery,
} from '@/redux/api/coolRxApi';
import { fgStat, fgStatsBlock } from '@/types/fortyguard';
import type { FgNormalDistribution } from '@/types/fortyguard';
import type {
  EstimateUnit,
  FgAnalyticType,
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


/**
 * Equity weighting for the diagnosis ranking.
 *
 * The Prescription page owns this as a user-adjustable control; the
 * diagnosis table shows the balanced ranking so the two views are
 * comparable before any weighting has been chosen.
 */
const DEFAULT_EQUITY_LAMBDA = 0.5;

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

/**
 * The four headline statistics, normalised.
 *
 * Two shapes reach this hook. The committed fixtures carry the API's raw
 * `stats_data` blob, with the statistics nested under `temperature_stats`; the
 * backend's own `/stats` endpoint returns them already flattened to
 * min/max/mean/std. Both describe the same measurement, so the hook normalises
 * rather than making every consumer branch on which one it got.
 *
 * Every field is nullable. A null renders as an em dash: 0 °C is a reading, and
 * printing it for an unmeasured district would look arctic rather than absent.
 */
export interface DistrictStats {
  readonly min: number | null;
  readonly max: number | null;
  readonly mean: number | null;
  readonly std: number | null;
  readonly count: number | null;
  readonly units: string | null;
}

interface UseDiagnosisResult {
  readonly activeAnalytic: FgAnalyticType;
  readonly meta: AnalyticMeta;
  readonly tiles: TileCollection | null;
  readonly domain: readonly [number, number];
  readonly stats: DistrictStats | null;
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
  const prioritiesQuery = useGetPrioritiesQuery(
    { projectId, equityLambda: DEFAULT_EQUITY_LAMBDA },
    { skip: USE_FIXTURES },
  );

  const tiles = useMemo<TileCollection | null>(() => {
    if (USE_FIXTURES) return fixtureTiles(activeAnalytic);
    if (tilesQuery.data === undefined) return null;
    return {
      type: 'FeatureCollection',
      features: tilesQuery.data.features,
    };
  }, [activeAnalytic, tilesQuery.data]);

  /**
   * Centre the map on the tiles that were actually measured.
   *
   * This used to return `DIAGNOSIS_CENTER` for every project — a constant from
   * the fixture module, fixed at 33.4755 °N. Central Phoenix measures 33.43 to
   * 33.455, so the viewport sat two kilometres north of its own data and the
   * district rendered off-screen: an empty grey panel with a correct legend and
   * a correct block count beside it. For Las Vegas and Tucson it was hundreds of
   * kilometres out.
   *
   * The bounds come from the geometry rather than the project's AOI because the
   * tiles are what is drawn, and a grid is clipped to whole cells.
   */
  const center = useMemo<readonly [number, number]>(() => {
    const features = tiles?.features ?? [];
    if (features.length === 0) return DIAGNOSIS_CENTER;

    let west = Infinity;
    let east = -Infinity;
    let south = Infinity;
    let north = -Infinity;

    for (const feature of features) {
      for (const ring of feature.geometry.coordinates) {
        for (const position of ring) {
          const [lon, lat] = position;
          if (lon < west) west = lon;
          if (lon > east) east = lon;
          if (lat < south) south = lat;
          if (lat > north) north = lat;
        }
      }
    }

    if (!Number.isFinite(west) || !Number.isFinite(south)) return DIAGNOSIS_CENTER;
    return [(west + east) / 2, (south + north) / 2];
  }, [tiles]);

  const stats = useMemo<DistrictStats | null>(() => {
    if (USE_FIXTURES) {
      const blob = fixtureStats(activeAnalytic);
      return {
        min: fgStat(blob, 'min'),
        max: fgStat(blob, 'max'),
        mean: fgStat(blob, 'mean'),
        std: fgStat(blob, 'std'),
        count: null,
        units: null,
      };
    }
    // `/stats` publishes a project-level summary *and* one run per analytic.
    // The summary is the temperature field, so using it on every tab put the
    // tcm figures under the wrong unit everywhere else: a district measured at
    // 34.63 °C rendered as "35 hours" of unbroken heat on Persistence, which is
    // not merely wrong but impossible. The per-analytic block was already in
    // the payload; this reads it.
    //
    // Exceedance is queried once per rung, so the run matching the threshold
    // the legend names is the one whose figures belong beside it.
    const run = statsQuery.data?.analyticRuns.find(
      (candidate) =>
        candidate.analyticType === activeAnalytic &&
        (activeAnalytic !== 'exceedance' ||
          candidate.thresholdC === FIXTURE_THRESHOLD_C),
    );
    const flat = run?.stats ?? statsQuery.data?.stats;
    if (flat === undefined) return null;
    return {
      min: flat.min ?? null,
      max: flat.max ?? null,
      mean: flat.mean ?? null,
      std: flat.std ?? null,
      count: flat.count ?? null,
      // Echoed from the response, never assumed. The live API sends no units
      // field for `tcm`, so this is null rather than a guessed "°C".
      units: flat.units ?? null,
    };
  }, [activeAnalytic, statsQuery.data]);

  const domain = useMemo<readonly [number, number]>(() => {
    if (USE_FIXTURES) return fixtureDomain(activeAnalytic);
    // From the measured range, not a constant. The placeholder [0, 1] left the
    // legend claiming a district spanned one degree from zero, and every tile
    // rendered at the top of the colour ramp.
    const lo = stats?.min;
    const hi = stats?.max;
    if (lo === null || lo === undefined || hi === null || hi === undefined) {
      return [0, 1];
    }
    // A district whose tiles are all one value would give a zero-width domain,
    // which is a divide-by-zero in every colour scale.
    return hi > lo ? [lo, hi] : [lo, lo + 1];
  }, [activeAnalytic, stats]);

  const priorities = useMemo<readonly TilePriority[]>(
    () =>
      USE_FIXTURES ? fixturePriorities(12) : (prioritiesQuery.data?.items ?? []),
    [prioritiesQuery.data],
  );

  const peakHourHistogram = useMemo<readonly number[]>(() => {
    if (USE_FIXTURES) return fixturePeakHourHistogram();
    // Counted from the ranked blocks rather than fetched: `peakHourLocal` is
    // already on each one, and a second endpoint for the same numbers could
    // disagree with the table beside it.
    const hours = new Array<number>(24).fill(0);
    let seen = 0;
    priorities.forEach((tile) => {
      const hour = tile.peakHourLocal;
      if (hour !== null && hour !== undefined && hour >= 0 && hour < 24) {
        hours[hour] = (hours[hour] ?? 0) + 1;
        seen += 1;
      }
    });
    return seen > 0 ? hours : [];
  }, [priorities]);

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
    /*
     * Only the fixtures carry a distribution.
     *
     * `stats_data.normal_temperature_distribution` is in the raw FortyGuard
     * response, and the backend's `/stats` publishes the four summary
     * statistics rather than the curve. So on live data this is empty and the
     * chart renders its own no-data state -- which is the honest outcome, not a
     * bug to paper over by synthesising a bell curve from mean and standard
     * deviation. That curve would look like a measurement and would not be one.
     *
     * The block is optional and its casing varies even within the fixtures --
     * the docs capitalise it, the live API does not -- so it is read through
     * `fgStatsBlock` rather than by property access.
     */
    if (!USE_FIXTURES) return [];
    const distribution = fgStatsBlock<FgNormalDistribution>(
      fixtureStats(activeAnalytic),
      'Normal_temperature_distribution',
    );
    const xs = distribution?.x_axis;
    const ys = distribution?.y_axis;
    if (xs === undefined || ys === undefined) return [];
    return xs.map((temperature, index) => ({
      temperature,
      density: ys[index] ?? 0,
    }));
  }, [activeAnalytic]);

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
    center,
    selectedTileKey,
    isLoading: tilesQuery.isLoading || statsQuery.isLoading,
    errorMessage,
    distributionPoints,
    onAnalyticChange,
    onSelectTile,
  };
}
