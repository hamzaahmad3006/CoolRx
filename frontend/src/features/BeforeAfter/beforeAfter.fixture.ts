import type { Estimate, TileCollection } from '@/types';
import {
  fixtureTileRecords,
  type GeneratedTile,
} from '@/features/Diagnosis/diagnosis.fixture';

/**
 * Before/After fixture.
 *
 * The baseline is the SAME field the Diagnosis screen renders — derived from
 * `fixtureTileRecords()` rather than generated independently, so the two screens
 * can never disagree about the same district.
 *
 * The counterfactual applies per-tile cooling with spatial falloff around each
 * treated block, because an intervention does not stop at a tile boundary. It is
 * a fixture, not a model run: the real counterfactual comes from the thermal
 * response model (SRS §9.3), and every figure here is labelled planning-grade in
 * the UI.
 */

const MODEL_VERSION = 'trm-2026.08.22-a3f1';

/** Cooling applied at the centre of each treated cluster, in °C. */
const TREATMENT_DELTA_C = 2.9;
/** Falloff radius in normalised district units. */
const FALLOFF = 0.055;

interface TreatmentSite {
  readonly u: number;
  readonly v: number;
  readonly strength: number;
}

/**
 * Treated sites, placed on the hottest parts of the field so the comparison
 * shows cooling where the diagnosis said the problem was.
 */
const SITES: readonly TreatmentSite[] = [
  { u: 0.58, v: 0.42, strength: 1.0 }, // commercial core — street trees
  { u: 0.66, v: 0.5, strength: 0.8 }, // arterial corridor — cool pavement
  { u: 0.5, v: 0.52, strength: 0.7 }, // transit plaza — misting + canopies
  { u: 0.62, v: 0.33, strength: 0.6 }, // secondary hotspot — trees
] as const;

function coolingAt(tile: GeneratedTile): number {
  let total = 0;
  for (const site of SITES) {
    const d2 = (tile.u - site.u) ** 2 + (tile.v - site.v) ** 2;
    total += site.strength * TREATMENT_DELTA_C * Math.exp(-d2 / FALLOFF);
  }
  // Saturation: stacked interventions in one tile show diminishing returns
  // rather than summing without limit (SRS §9.3.2).
  return Math.min(TREATMENT_DELTA_C * 1.35, total);
}

const RECORDS = fixtureTileRecords();

interface TileWithDelta {
  readonly record: GeneratedTile;
  readonly beforeC: number;
  readonly afterC: number;
  readonly deltaC: number;
}

const WITH_DELTA: readonly TileWithDelta[] = RECORDS.map((record) => {
  const cooling = coolingAt(record);
  const beforeC = record.temperatureC;
  const afterC = Math.round((beforeC - cooling) * 10) / 10;
  return {
    record,
    beforeC,
    afterC,
    deltaC: Math.round((afterC - beforeC) * 10) / 10,
  };
});

/** Tiles whose predicted change is material enough to call treated. */
const TREATED = WITH_DELTA.filter((tile) => tile.deltaC <= -0.2);

function toCollection(
  pick: (tile: TileWithDelta) => number,
): TileCollection {
  return {
    type: 'FeatureCollection',
    features: WITH_DELTA.map((tile) => ({
      type: 'Feature' as const,
      properties: {
        tile_key: tile.record.tileKey,
        value: pick(tile),
      },
      geometry: {
        type: 'Polygon' as const,
        coordinates: [tile.record.ring.map(([lon, lat]) => [lon, lat] as const)],
      },
    })),
  };
}

export const BEFORE_TILES: TileCollection = toCollection((tile) => tile.beforeC);
export const AFTER_TILES: TileCollection = toCollection((tile) => tile.afterC);

/**
 * ONE domain spanning both fields.
 *
 * Computed across before AND after together so identical colours mean identical
 * temperatures on both sides of the divider. Scaling each side independently
 * would make the "after" side look cooler than it is (SRS §28.8).
 */
export const SHARED_DOMAIN: readonly [number, number] = (() => {
  const all = WITH_DELTA.flatMap((tile) => [tile.beforeC, tile.afterC]);
  const min = all.reduce((acc, v) => Math.min(acc, v), Number.POSITIVE_INFINITY);
  const max = all.reduce((acc, v) => Math.max(acc, v), Number.NEGATIVE_INFINITY);
  return [Math.floor(min), Math.ceil(max)];
})();

/** Mean predicted cooling across treated tiles, with its interval. */
export const MEAN_DELTA: Estimate = (() => {
  const mean =
    TREATED.reduce((sum, tile) => sum + tile.deltaC, 0) / (TREATED.length || 1);
  const rounded = Math.round(mean * 10) / 10;
  return {
    value: rounded,
    // Interval width reflects the quantile models' spread on held-out districts.
    ciLow: Math.round((rounded - 0.7) * 10) / 10,
    ciHigh: Math.round((rounded + 0.7) * 10) / 10,
    unit: 'celsius',
    modelVersion: MODEL_VERSION,
  };
})();

/** Histogram of predicted ΔT across treated tiles, for the distribution chart. */
export function deltaHistogram(bins = 14): readonly {
  deltaC: number;
  count: number;
}[] {
  if (TREATED.length === 0) return [];

  const deltas = TREATED.map((tile) => tile.deltaC);
  const min = deltas.reduce((acc, v) => Math.min(acc, v), Number.POSITIVE_INFINITY);
  const max = deltas.reduce((acc, v) => Math.max(acc, v), Number.NEGATIVE_INFINITY);
  const span = max - min || 1;

  const counts = new Array<number>(bins).fill(0);
  for (const delta of deltas) {
    const index = Math.min(bins - 1, Math.floor(((delta - min) / span) * bins));
    counts[index] = (counts[index] ?? 0) + 1;
  }

  return counts.map((count, index) => ({
    deltaC: Math.round((min + (index / bins) * span) * 10) / 10,
    count,
  }));
}

export const TREATED_TILE_COUNT = TREATED.length;
export const MAX_ABS_DELTA = Math.max(
  ...TREATED.map((tile) => Math.abs(tile.deltaC)),
  1,
);
