'use client';

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { FG_LIMITS, USE_FIXTURES } from '@/constants';
import {
  areaSqMi,
  boxAround,
  boxToFeatureCollection,
  estimateCredits,
  estimateTileCount,
  preflight,
  type AoiIssue,
  type BoundingBox,
} from '@/lib/aoi';
import {
  useCreateProjectMutation,
  useStartDiagnosisMutation,
  useValidateAoiMutation,
} from '@/redux/api/coolRxApi';
import { useAppDispatch, useAppSelector } from '@/redux/hooks';
import {
  setActiveJob,
  setCurrentProject,
  setGranularity,
  setStartDate,
  setStartTime,
  setThresholdC,
} from '@/redux/slices/sessionSlice';
import type { FgGranularity } from '@/types';


/** Downtown Phoenix — the SRS's primary demo district. */
const DEFAULT_CENTER: readonly [number, number] = [-112.074, 33.448];

/** ~2 km per side is about 1.5 mi², comfortably inside the 10 mi² cap. */
const DEFAULT_EDGE_KM = 2.0;
export const MIN_EDGE_KM = 0.5;
export const MAX_EDGE_KM = 6.0;

/**
 * Delay before asking the server to validate. Long enough that dragging the
 * slider does not fire a request per pixel, short enough to feel immediate once
 * the user stops.
 */
const VALIDATE_DEBOUNCE_MS = 400;

interface UseAoiStudioResult {
  readonly box: BoundingBox;
  readonly centerLon: number;
  readonly centerLat: number;
  readonly edgeKm: number;
  readonly startDate: string;
  readonly startTime: string;
  readonly granularity: FgGranularity;
  readonly thresholdC: number;
  readonly buildLadder: boolean;
  /** Instant local estimate, recomputed on every change. */
  readonly localAreaSqMi: number;
  readonly maxAreaSqMi: number;
  /** Server's figure once it answers; null while unknown. */
  readonly serverAreaSqMi: number | null;
  readonly issues: readonly AoiIssue[];
  readonly isValid: boolean;
  readonly isValidating: boolean;
  /** True until the server has confirmed the current box. */
  readonly isUnconfirmed: boolean;
  readonly estimatedTiles: number;
  readonly estimatedCredits: number;
  readonly isSubmitting: boolean;
  readonly submitError: string | null;
  readonly onRecenter: (lon: number, lat: number) => void;
  readonly onEdgeKmChange: (km: number) => void;
  readonly onStartDateChange: (date: string) => void;
  readonly onStartTimeChange: (time: string) => void;
  readonly onGranularityChange: (granularity: FgGranularity) => void;
  readonly onThresholdChange: (celsius: number) => void;
  readonly onBuildLadderChange: (enabled: boolean) => void;
  readonly onSubmit: () => void;
}

export function useAoiStudio(): UseAoiStudioResult {
  const dispatch = useAppDispatch();
  const router = useRouter();

  const startDate = useAppSelector((state) => state.session.startDate);
  const startTime = useAppSelector((state) => state.session.startTime);
  const granularity = useAppSelector((state) => state.session.granularity);
  const thresholdC = useAppSelector((state) => state.session.thresholdC);

  const [centerLon, setCenterLon] = useState(DEFAULT_CENTER[0]);
  const [centerLat, setCenterLat] = useState(DEFAULT_CENTER[1]);
  const [edgeKm, setEdgeKm] = useState(DEFAULT_EDGE_KM);
  const [buildLadder, setBuildLadder] = useState(true);
  // The server's verdict is stored with the box it was computed for, so it can be
  // matched against the current box during render instead of being cleared by an
  // effect every time the box moves. That also drops a response the box has since
  // moved past, which previously landed and overwrote the verdict for a box the
  // user was no longer looking at.
  const [serverVerdict, setServerVerdict] = useState<{
    readonly box: BoundingBox;
    readonly areaSqMi: number;
    readonly issues: readonly AoiIssue[];
  } | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [validateAoi, validateState] = useValidateAoiMutation();
  const [createProject, createState] = useCreateProjectMutation();
  const [startDiagnosis, diagnoseState] = useStartDiagnosisMutation();

  const box = useMemo(
    () => boxAround(centerLon, centerLat, edgeKm),
    [centerLon, centerLat, edgeKm],
  );

  const localAreaSqMi = useMemo(() => areaSqMi(box), [box]);

  const localIssues = useMemo(
    () => preflight({ box, startDate }),
    [box, startDate],
  );

  /**
   * Ask the server once the box settles.
   *
   * The local check uses a spherical approximation and the server uses the
   * WGS84 ellipsoid, so near the cap they can disagree. The server's answer
   * replaces the local one rather than being merged with it — two sources of
   * truth for "is this valid" is how a UI ends up contradicting itself.
   */
  useEffect(() => {
    if (USE_FIXTURES) return undefined;

    const timer = window.setTimeout(() => {
      void validateAoi({ aoi: boxToFeatureCollection(box) as never })
        .unwrap()
        .then((result) => {
          setServerVerdict({
            box,
            areaSqMi: result.areaSqMi,
            issues: result.violations.map((violation) => ({
              code: violation.code as AoiIssue['code'],
              message: violation.message,
              field: violation.field,
            })),
          });
        })
        .catch(() => {
          // Leave the local verdict standing. A validation endpoint that is down
          // must not block placing an AOI; submission will surface the error.
        });
    }, VALIDATE_DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
  }, [box, validateAoi]);

  // `box` is memoised on the three inputs that define it, so identity is the
  // right test: any move produces a new object and retires the stored verdict.
  const confirmed = serverVerdict?.box === box ? serverVerdict : null;
  const serverIssues = confirmed?.issues ?? null;
  const serverAreaSqMi = confirmed?.areaSqMi ?? null;

  const issues = serverIssues ?? localIssues;
  const isValid = issues.length === 0;
  const isUnconfirmed = !USE_FIXTURES && serverIssues === null;

  const onRecenter = useCallback((lon: number, lat: number): void => {
    setCenterLon(lon);
    setCenterLat(lat);
  }, []);

  const onEdgeKmChange = useCallback((km: number): void => {
    setEdgeKm(Math.min(MAX_EDGE_KM, Math.max(MIN_EDGE_KM, km)));
  }, []);

  const onStartDateChange = useCallback(
    (date: string): void => {
      dispatch(setStartDate(date));
    },
    [dispatch],
  );

  const onStartTimeChange = useCallback(
    (time: string): void => {
      dispatch(setStartTime(time));
    },
    [dispatch],
  );

  const onGranularityChange = useCallback(
    (value: FgGranularity): void => {
      dispatch(setGranularity(value));
    },
    [dispatch],
  );

  const onThresholdChange = useCallback(
    (celsius: number): void => {
      dispatch(setThresholdC(celsius));
    },
    [dispatch],
  );

  const onSubmit = useCallback((): void => {
    setSubmitError(null);

    if (USE_FIXTURES) {
      // Fixture mode has no backend to create against; go straight to the
      // preset district the fixtures describe, rather than pretending a new
      // project was created.
      router.push('/p/phoenix-central/diagnose');
      return;
    }

    void (async () => {
      try {
        const project = await createProject({
          name: `District at ${centerLat.toFixed(3)}, ${centerLon.toFixed(3)}`,
          city: 'Unknown',
          state: 'AZ',
          aoi: boxToFeatureCollection(box) as never,
        }).unwrap();

        dispatch(setCurrentProject(project.id));

        const job = await startDiagnosis({
          projectId: project.id,
          body: {
            startDate,
            startTime,
            granularity,
            thresholdC,
            buildLadder,
          },
        }).unwrap();

        dispatch(setActiveJob(job.jobId));
        router.push(`/p/${project.id}/diagnose`);
      } catch {
        setSubmitError(
          'We couldn’t start the analysis. Your area is unchanged — try again.',
        );
      }
    })();
  }, [
    box,
    buildLadder,
    centerLat,
    centerLon,
    createProject,
    dispatch,
    granularity,
    router,
    startDate,
    startDiagnosis,
    startTime,
    thresholdC,
  ]);

  return {
    box,
    centerLon,
    centerLat,
    edgeKm,
    startDate,
    startTime,
    granularity,
    thresholdC,
    buildLadder,
    localAreaSqMi,
    maxAreaSqMi: FG_LIMITS.maxAoiSqMi,
    serverAreaSqMi,
    issues,
    isValid,
    isValidating: validateState.isLoading,
    isUnconfirmed,
    estimatedTiles: estimateTileCount(box, granularity),
    estimatedCredits: estimateCredits(buildLadder),
    isSubmitting: createState.isLoading || diagnoseState.isLoading,
    submitError,
    onRecenter,
    onEdgeKmChange,
    onStartDateChange,
    onStartTimeChange,
    onGranularityChange,
    onThresholdChange,
    onBuildLadderChange: setBuildLadder,
    onSubmit,
  };
}
