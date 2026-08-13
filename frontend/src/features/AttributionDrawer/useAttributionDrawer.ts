'use client';

import { useCallback, useEffect, useMemo } from 'react';

import { useGetAttributionQuery, useGetExposureQuery } from '@/redux/api/coolRxApi';
import { useAppDispatch, useAppSelector } from '@/redux/hooks';
import { closeAttributionDrawer } from '@/redux/slices/uiSlice';
import type { Attribution, Exposure, TileFeatures } from '@/types';

import {
  ATTRIBUTION_FIXTURE,
  EXPOSURE_FIXTURE,
  TILE_FEATURES_FIXTURE,
} from './attribution.fixture';

const USE_FIXTURES = process.env.NEXT_PUBLIC_USE_FIXTURES !== 'false';

interface UseAttributionDrawerArgs {
  readonly projectId: string;
}

interface UseAttributionDrawerResult {
  readonly isOpen: boolean;
  readonly tileKey: string | null;
  readonly attribution: Attribution | null;
  readonly features: TileFeatures | null;
  readonly exposure: Exposure | null;
  readonly isLoading: boolean;
  /**
   * Set when the tile has no attribution. Distinct from an error: a tile the
   * model declined to predict is a legitimate outcome that must be explained,
   * not reported as a failure.
   */
  readonly unavailableReason: string | null;
  readonly errorMessage: string | null;
  readonly onClose: () => void;
}

export function useAttributionDrawer({
  projectId,
}: UseAttributionDrawerArgs): UseAttributionDrawerResult {
  const dispatch = useAppDispatch();
  const isOpen = useAppSelector((state) => state.ui.attributionDrawerOpen);
  const tileKey = useAppSelector((state) => state.ui.selectedTileKey);

  // Skipped while closed so opening the Diagnosis page does not fetch
  // attribution for every project the user merely looks at.
  const skip = USE_FIXTURES || !isOpen || tileKey === null;

  const attributionQuery = useGetAttributionQuery(projectId, { skip });
  const exposureQuery = useGetExposureQuery(projectId, { skip });

  const onClose = useCallback((): void => {
    dispatch(closeAttributionDrawer());
  }, [dispatch]);

  // Escape closes the drawer. Registered only while open, so it cannot swallow
  // the key from another overlay that opens later.
  useEffect(() => {
    if (!isOpen) return undefined;

    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isOpen, onClose]);

  const attribution = useMemo<Attribution | null>(() => {
    if (!isOpen || tileKey === null) return null;
    if (USE_FIXTURES) return { ...ATTRIBUTION_FIXTURE, tileKey };
    return (
      attributionQuery.data?.items.find((item) => item.tileKey === tileKey) ?? null
    );
  }, [isOpen, tileKey, attributionQuery.data]);

  const exposure = useMemo<Exposure | null>(() => {
    if (!isOpen || tileKey === null) return null;
    if (USE_FIXTURES) return { ...EXPOSURE_FIXTURE, tileKey };
    return exposureQuery.data?.items.find((item) => item.tileKey === tileKey) ?? null;
  }, [isOpen, tileKey, exposureQuery.data]);

  const features = useMemo<TileFeatures | null>(() => {
    if (!isOpen || tileKey === null) return null;
    // Tile features have no dedicated endpoint yet; the drawer reads them from
    // the attribution payload once the backend joins them. Until then the
    // fixture supplies the shape and live mode renders the unavailable state
    // rather than a fabricated composition.
    if (USE_FIXTURES) return { ...TILE_FEATURES_FIXTURE, tileKey };
    return null;
  }, [isOpen, tileKey]);

  const isLoading =
    !USE_FIXTURES &&
    isOpen &&
    (attributionQuery.isLoading || exposureQuery.isLoading);

  const errorMessage =
    !USE_FIXTURES && (attributionQuery.isError || exposureQuery.isError)
      ? 'We couldn’t load the drivers for this block.'
      : null;

  const unavailableReason =
    isOpen && !isLoading && errorMessage === null && attribution === null
      ? 'The model did not produce an attribution for this block. This usually ' +
        'means its land-cover data fell outside the range the model was trained on.'
      : null;

  return {
    isOpen,
    tileKey,
    attribution,
    features,
    exposure,
    isLoading,
    unavailableReason,
    errorMessage,
    onClose,
  };
}
