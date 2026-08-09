import type {
  FgAnalyticType,
  FgStatsData,
  TileCollection,
  TilePriority,
} from '@/types';

/**
 * Diagnosis fixture — Phoenix · Encanto district.
 *
 * The tile grid is GENERATED rather than hardcoded: a 40 × 30 lattice over the
 * district bounding box with a deterministic synthetic heat field. Deterministic
 * matters — a seeded field means the choropleth, the statistics and the ranked
 * table stay identical across runs, so a golden-image test is possible and the
 * demo looks the same every time.
 *
 * ⚠️ Fixture data. Not a measurement. Surfaced in the UI by the "Fixture data"
 * badge (SRS FR-022).
 */

const COLS = 40;
const ROWS = 30;

/** District bounding box: [west, south, east, north]. */
const BBOX = [-112.1005, 33.4655, -112.0755, 33.4855] as const;

export const DIAGNOSIS_CENTER: readonly [number, number] = [
  (BBOX[0] + BBOX[2]) / 2,
  (BBOX[1] + BBOX[3]) / 2,
];

/** Deterministic value noise — no Math.random, so the fixture never drifts. */
function hash2(x: number, y: number): number {
  const n = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return n - Math.floor(n);
}

interface FieldInputs {
  readonly u: number; // 0–1 across the district, west → east
  readonly v: number; // 0–1 across the district, south → north
}

/**
 * Synthetic thermal field with structure a planner would recognise: a hot
 * commercial core with low canopy, a cooler park in the north-west, and a warm
 * arterial corridor running east.
 */
function temperatureAt({ u, v }: FieldInputs): number {
  const core = Math.exp(-(((u - 0.58) ** 2) / 0.055 + ((v - 0.42) ** 2) / 0.05));
  const park = Math.exp(-(((u - 0.18) ** 2) / 0.02 + ((v - 0.78) ** 2) / 0.02));
  const corridor = Math.exp(-((v - 0.5) ** 2) / 0.004);

  const base = 36.4;
  const value =
    base + core * 7.4 + corridor * 1.6 - park * 3.4 + (hash2(u * 97, v * 61) - 0.5) * 0.9;

  return Math.round(value * 10) / 10;
}

/** Hours above the 35 °C threshold, derived from the peak so the two agree. */
function exceedanceAt(peakC: number): number {
  if (peakC <= 35) return 0;
  return Math.min(13, Math.round((peakC - 35) * 1.35));
}

/** Longest continuous run past threshold — always ≤ exceedance hours. */
function persistenceAt(exceedanceHours: number, u: number, v: number): number {
  if (exceedanceHours === 0) return 0;
  const fragmentation = 0.62 + hash2(u * 13, v * 29) * 0.3;
  return Math.max(1, Math.round(exceedanceHours * fragmentation));
}

/** Peak hour, UTC. Phoenix is UTC-7, so 22–23 UTC is mid-afternoon local. */
function peakHourUtcAt(u: number, v: number): number {
  return 21 + Math.round(hash2(u * 41, v * 83) * 2);
}

export interface GeneratedTile {
  readonly tileKey: string;
  readonly u: number;
  readonly v: number;
  readonly ring: readonly [number, number][];
  readonly temperatureC: number;
  readonly exceedanceHours: number;
  readonly persistenceHours: number;
  readonly peakHourUtc: number;
}

function generateTiles(): readonly GeneratedTile[] {
  const [west, south, east, north] = BBOX;
  const dx = (east - west) / COLS;
  const dy = (north - south) / ROWS;
  const tiles: GeneratedTile[] = [];

  for (let row = 0; row < ROWS; row += 1) {
    for (let col = 0; col < COLS; col += 1) {
      const u = (col + 0.5) / COLS;
      const v = (row + 0.5) / ROWS;

      const x0 = west + col * dx;
      const y0 = south + row * dy;
      const x1 = x0 + dx;
      const y1 = y0 + dy;

      const temperatureC = temperatureAt({ u, v });
      const exceedanceHours = exceedanceAt(temperatureC);

      tiles.push({
        tileKey: `B-${String(row * COLS + col).padStart(3, '0')}`,
        u,
        v,
        // Closed ring — first coordinate repeated last, as the API requires.
        ring: [
          [x0, y0],
          [x1, y0],
          [x1, y1],
          [x0, y1],
          [x0, y0],
        ],
        temperatureC,
        exceedanceHours,
        persistenceHours: persistenceAt(exceedanceHours, u, v),
        peakHourUtc: peakHourUtcAt(u, v),
      });
    }
  }

  return tiles;
}

const TILES = generateTiles();

/** Phoenix is UTC-7 year round (no DST). */
export const TIMEZONE_OFFSET_HOURS = -7;

function valueFor(tile: GeneratedTile, analytic: FgAnalyticType): number {
  switch (analytic) {
    case 'tcm':
      return tile.temperatureC;
    case 'exceedance':
      return tile.exceedanceHours;
    case 'persistence':
      return tile.persistenceHours;
    case 'time_of_measure':
      return tile.peakHourUtc;
  }
}

/** Build the GeoJSON collection for one analytic layer. */
export function fixtureTiles(analytic: FgAnalyticType): TileCollection {
  return {
    type: 'FeatureCollection',
    features: TILES.map((tile) => ({
      type: 'Feature' as const,
      properties: {
        tile_key: tile.tileKey,
        value: valueFor(tile, analytic),
      },
      geometry: {
        type: 'Polygon' as const,
        coordinates: [tile.ring.map(([lon, lat]) => [lon, lat] as const)],
      },
    })),
  };
}

/** Value domain for the colour ramp, per analytic. */
export function fixtureDomain(
  analytic: FgAnalyticType,
): readonly [number, number] {
  const values = TILES.map((tile) => valueFor(tile, analytic));
  const min = values.reduce((acc, v) => Math.min(acc, v), Number.POSITIVE_INFINITY);
  const max = values.reduce((acc, v) => Math.max(acc, v), Number.NEGATIVE_INFINITY);
  return [Math.floor(min), Math.ceil(max)];
}

/** Statistics block, shaped exactly like the API's `stats_data`. */
export function fixtureStats(analytic: FgAnalyticType): FgStatsData {
  const values = TILES.map((tile) => valueFor(tile, analytic)).sort((a, b) => a - b);
  const n = values.length;
  const mean = values.reduce((sum, v) => sum + v, 0) / n;
  const variance = values.reduce((sum, v) => sum + (v - mean) ** 2, 0) / n;

  const min = values[0] ?? 0;
  const max = values[n - 1] ?? 0;

  // Normalised density curve for the distribution chart.
  const bins = 40;
  const span = max - min || 1;
  const counts = new Array<number>(bins).fill(0);
  for (const value of values) {
    const index = Math.min(bins - 1, Math.floor(((value - min) / span) * bins));
    counts[index] = (counts[index] ?? 0) + 1;
  }
  const peak = counts.reduce((acc, c) => Math.max(acc, c), 1);

  const frequency: Record<string, number> = {};
  counts.forEach((count, index) => {
    const label = (min + (index / bins) * span).toFixed(1);
    frequency[label] = count;
  });

  return {
    Temperature_stats: {
      Minimum: Math.round(min * 10) / 10,
      Maximum: Math.round(max * 10) / 10,
      Mean: Math.round(mean * 10) / 10,
      Standard_deviation: Math.round(Math.sqrt(variance) * 10) / 10,
    },
    Overall_temperature_distribution: values,
    Normal_temperature_distribution: {
      x_axis: counts.map((_, index) => min + (index / bins) * span),
      y_axis: counts.map((count) => count / peak),
    },
    Temperature_frequency: frequency,
    units: analytic === 'tcm' ? 'celsius' : 'hour',
  };
}

/**
 * Ranked priority blocks. Ordering is by person-heat-hours — population times
 * dangerous hours — which is a derived quantity with units rather than an
 * invented index (SRS §9.5.1).
 */
export function fixturePriorities(limit = 12): readonly TilePriority[] {
  const withExposure = TILES.filter((tile) => tile.exceedanceHours > 0).map(
    (tile) => {
      // Denser population toward the commercial core and the corridor.
      const density =
        420 + Math.exp(-(((tile.u - 0.55) ** 2) / 0.09)) * 900 * (0.7 + hash2(tile.u * 7, tile.v * 11) * 0.6);
      const population = Math.round(density);
      const svi = Math.min(0.98, 0.35 + hash2(tile.u * 53, tile.v * 17) * 0.6);
      const personHeatHours = population * tile.exceedanceHours;

      const riskLevel =
        tile.persistenceHours >= 8
          ? ('extreme' as const)
          : tile.persistenceHours >= 5
            ? ('high' as const)
            : tile.persistenceHours >= 2
              ? ('moderate' as const)
              : ('low' as const);

      return {
        tileKey: tile.tileKey,
        rank: 0,
        riskLevel,
        exceedanceHours: tile.exceedanceHours,
        persistenceHours: tile.persistenceHours,
        peakHourLocal: (tile.peakHourUtc + 24 + TIMEZONE_OFFSET_HOURS) % 24,
        population,
        personHeatHours,
        equityWeightedPhh: Math.round(personHeatHours * (1 + svi)),
      };
    },
  );

  return withExposure
    .sort((a, b) => b.equityWeightedPhh - a.equityWeightedPhh)
    .slice(0, limit)
    .map((tile, index) => ({ ...tile, rank: index + 1 }));
}

/** Per-hour count of how many blocks peak in each local hour. */
export function fixturePeakHourHistogram(): readonly number[] {
  const histogram = new Array<number>(24).fill(0);
  for (const tile of TILES) {
    if (tile.exceedanceHours === 0) continue;
    const local = (tile.peakHourUtc + 24 + TIMEZONE_OFFSET_HOURS) % 24;
    histogram[local] = (histogram[local] ?? 0) + 1;
  }
  return histogram;
}

export const FIXTURE_THRESHOLD_C = 35;
export const FIXTURE_TILE_COUNT = TILES.length;

/**
 * Raw generated tile records.
 *
 * Exposed so the Before/After fixture can derive a counterfactual field from the
 * SAME baseline the Diagnosis screen shows. Deriving it from a second,
 * independent field would let the two screens disagree about the same district.
 */
export function fixtureTileRecords(): readonly GeneratedTile[] {
  return TILES;
}
