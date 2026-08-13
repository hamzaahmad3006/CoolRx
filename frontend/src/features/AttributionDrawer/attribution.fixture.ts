/**
 * Fixture for the attribution drawer.
 *
 * Shaped, not sampled. These are structurally realistic values used to exercise
 * layout before the model exists — including the cases that are easy to forget:
 * a tile with partial land cover, and a tile with no attribution at all.
 *
 * The numbers here never reach a report. `USE_FIXTURES` gates them, the top bar
 * shows the fixture badge whenever it is on, and no fixture value is ever written
 * to `plans` or a PDF.
 */

import type { Attribution, Exposure, TileFeatures } from '@/types';

/** Matches the Prescription fixture so both surfaces cite one model version. */
const MODEL_VERSION = 'trm-2026.08.22-a3f1';

export const FIXTURE_TILE_KEY = '9tbq2p3xj';

export const ATTRIBUTION_FIXTURE: Attribution = {
  tileKey: FIXTURE_TILE_KEY,
  modelVersion: MODEL_VERSION,
  anomaly: {
    value: 3.4,
    ciLow: 2.6,
    ciHigh: 4.1,
    unit: 'celsius',
    modelVersion: MODEL_VERSION,
  },
  topDriver: 'impervious_pct',
  drivers: [
    {
      feature: 'impervious_pct',
      label: 'Paved and built surface',
      contributionC: 1.9,
      share: 0.42,
    },
    {
      feature: 'canopy_pct',
      label: 'Missing tree canopy',
      contributionC: 1.4,
      share: 0.31,
    },
    {
      feature: 'albedo_proxy',
      label: 'Dark surface materials',
      contributionC: 0.6,
      share: 0.13,
    },
    {
      feature: 'openness_proxy',
      label: 'Trapped heat between buildings',
      contributionC: 0.3,
      share: 0.07,
    },
    {
      feature: 'dist_to_water_m',
      label: 'Distance from water',
      contributionC: 0.2,
      share: 0.04,
    },
    {
      feature: 'elevation_m',
      label: 'Elevation',
      contributionC: -0.1,
      share: 0.02,
    },
  ],
};

/**
 * Deliberately incomplete: `buildingPct` and `localReliefM` are null.
 *
 * This is the realistic case, not an edge case — NLCD has genuine coverage gaps.
 * Keeping it in the fixture means the donut's unmeasured arc and the feature
 * list's "not measured" rows are exercised every time the drawer is opened in
 * development, rather than discovered in front of a judge.
 */
export const TILE_FEATURES_FIXTURE: TileFeatures = {
  tileKey: FIXTURE_TILE_KEY,
  canopyPct: 4.2,
  imperviousPct: 61.5,
  buildingPct: null,
  waterPct: 0.0,
  grassShrubPct: 8.1,
  albedoProxy: 0.14,
  opennessProxy: 0.72,
  elevationM: 331.0,
  localReliefM: null,
  distToWaterM: 1840.0,
  districtMeanC: 41.2,
};

export const EXPOSURE_FIXTURE: Exposure = {
  tileKey: FIXTURE_TILE_KEY,
  population: 412.0,
  pctOver65: 18.4,
  pctPoverty: 27.9,
  sviScore: 0.81,
  sviSourceGeoid: '04013108102',
  assets: {
    busStop: 2,
    school: 1,
    park: 0,
    playground: 0,
    hospital: 0,
  },
};
