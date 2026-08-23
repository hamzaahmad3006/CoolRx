/**
 * FortyGuard Temperature API — response shapes.
 *
 * ⚠️ Every field below is taken from FortyGuard's published documentation
 * (Create Heatmap · Environmental Parameters · Check Status · Known Limitations).
 * No field is invented. If a shape is not documented it is marked and modelled
 * defensively rather than guessed — see SRS §11.5 for the full list of
 * documentation contradictions and §33 for the open questions.
 *
 * The frontend never calls FortyGuard directly; the API key is server-side only
 * (SRS §18.1). These types describe what the CoolRx backend proxies through.
 */

/* ─────────────────────────────────────────────────────────────────────────────
 * Request parameters
 * ────────────────────────────────────────────────────────────────────────────*/

/** The only granularity values the API accepts, in metres. */
export type FgGranularity = 60 | 80 | 100;

/**
 * Documented filter types. `4` (range of days) appears on the Create Heatmap
 * page but Known Limitations states filter_type "must be 1, 2, or 3" — see
 * contradiction C-2. CoolRx targets 1–3 only until verified.
 */
export type FgFilterType = 1 | 2 | 3;

/**
 * Analytic types on `POST /v1/heatmap`.
 * - `tcm`              temperature snapshot, °C per tile
 * - `time_of_measure`  hour of day (0–23, UTC) of peak temperature
 * - `exceedance`       count of hours past the threshold
 * - `persistence`      longest continuous run of hours past the threshold
 */
export type FgAnalyticType =
  | 'tcm'
  | 'time_of_measure'
  | 'exceedance'
  | 'persistence';

/** Threshold direction for exceedance / persistence. */
export type FgDirection = 'above' | 'below';

/** Documented activity lifecycle states. */
export type FgActivityStatus = 'Processing' | 'Completed' | 'Failed';

/**
 * Units are read from `stats_data.units` rather than assumed — hour-valued
 * analytics must never be labelled °C.
 */
export type FgUnits = 'hour' | 'celsius';

/* ─────────────────────────────────────────────────────────────────────────────
 * GeoJSON (minimal, closed-ring polygon only — the API requires a closed ring)
 * ────────────────────────────────────────────────────────────────────────────*/

/** [longitude, latitude] */
export type FgCoordinate = readonly [number, number];

export interface FgPolygonGeometry {
  readonly type: 'Polygon';
  /** Linear rings. First and last coordinate must be identical. */
  readonly coordinates: readonly FgCoordinate[][];
}

export interface FgFeature<TProperties extends object = Record<string, never>> {
  readonly type: 'Feature';
  readonly properties: TProperties;
  readonly geometry: FgPolygonGeometry;
}

export interface FgFeatureCollection<
  TProperties extends object = Record<string, never>,
> {
  readonly type: 'FeatureCollection';
  readonly features: readonly FgFeature<TProperties>[];
}

/** Properties carried on each returned heatmap tile. */
export interface FgTileProperties {
  /** Tile value in the analytic's units. `null` means missing — NEVER zero. */
  readonly value: number | null;
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Statistics block (`result.stats_data`)
 * ────────────────────────────────────────────────────────────────────────────*/

/**
 * The documented spelling. The live API sends the same four values lower-cased,
 * so read them through `fgStat` rather than by property access.
 */
export interface FgTemperatureStats {
  readonly Minimum?: number;
  readonly Maximum?: number;
  readonly Mean?: number;
  readonly Standard_deviation?: number;
  readonly minimum?: number;
  readonly maximum?: number;
  readonly mean?: number;
  readonly standard_deviation?: number;
}

export interface FgNormalDistribution {
  readonly x_axis: readonly number[];
  readonly y_axis: readonly number[];
}

/**
 * The API's `stats_data` block.
 *
 * Every field is optional and every field may arrive under either casing. The
 * documentation capitalises these keys; the live API sends them lower-cased —
 * `normal_temperature_distribution`, `temperature_stats`. Reading only the
 * documented spelling made the diagnosis page throw
 * "Cannot destructure property 'x_axis' of 'stats.Normal_temperature_distribution'"
 * the first time it was pointed at the real backend.
 *
 * The contents also genuinely vary by analytic type — an exceedance response has
 * no temperature distribution — so a missing block is normal rather than an
 * error. Read these through `fgStatsBlock`, which handles both.
 */
export interface FgStatsData {
  readonly Temperature_stats?: FgTemperatureStats;
  readonly temperature_stats?: FgTemperatureStats;
  readonly Overall_temperature_distribution?: readonly number[];
  readonly overall_temperature_distribution?: readonly number[];
  readonly Normal_temperature_distribution?: FgNormalDistribution;
  readonly normal_temperature_distribution?: FgNormalDistribution;
  /** Histogram-style frequency counts, keyed by bin label. */
  readonly Temperature_frequency?: Readonly<Record<string, number>>;
  readonly temperature_frequency?: Readonly<Record<string, number>>;
  readonly units?: FgUnits;
}

/**
 * One block from `stats_data`, under whichever casing it arrived in.
 *
 * Mirrors `read_stat` on the backend, which solved the same mismatch. Returns
 * null rather than throwing: an analytic type that omits a block is a normal
 * response, not a failure.
 */
export function fgStatsBlock<T>(
  stats: FgStatsData | null | undefined,
  key: string,
): T | null {
  if (stats === null || stats === undefined) return null;
  const record = stats as unknown as Record<string, unknown>;
  const value = record[key] ?? record[key.toLowerCase()];
  return (value ?? null) as T | null;
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Heatmap result
 * ────────────────────────────────────────────────────────────────────────────*/

export interface FgHeatmapResult {
  readonly map_data: FgFeatureCollection<FgTileProperties>;
  readonly stats_data: FgStatsData;
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Environmental parameters
 *
 * On API Basic the `analysis` list is capped at 3 parameters per request, so
 * CoolRx requests exactly heat index, wet-bulb and relative humidity.
 * Values may be `null` (missing) and legacy records may carry `-999`; both mean
 * missing and must never be read as zero.
 * ────────────────────────────────────────────────────────────────────────────*/

export type FgEnvParameterName =
  | 'heat_index_celsius'
  | 'apparent_temperature_celsius'
  | 'wet_bulb_temperature_celsius'
  | 'relative_humidity_percent'
  | 'precipitation_mm'
  | 'cloud_cover_octas'
  | 'elevation'
  | 'air_quality:idx'
  | 'air_quality_pm2p5:idx'
  | 'air_quality_pm10:idx'
  | 'air_quality_no2:idx'
  | 'aqi_us_co'
  | 'air_quality_o3:idx'
  | 'air_quality_so2:idx'
  | 'methane_ppb'
  | 'co2_ppm'
  | 'solar_irradiance';

/** The three parameters CoolRx requests on API Basic. */
export type FgBasicEnvParameter = Extract<
  FgEnvParameterName,
  | 'heat_index_celsius'
  | 'wet_bulb_temperature_celsius'
  | 'relative_humidity_percent'
>;

/** A time-aligned series. `null` entries are missing values. */
export type FgParameterSeries = readonly (number | null)[];

export interface FgTimeRange {
  readonly start: string;
  readonly end: string;
  readonly interval: string;
  readonly count: number;
}

export interface FgEnvMetadata {
  readonly timezone: string;
  /** Used to convert `time_of_measure` UTC hours into district-local time. */
  readonly timezone_offset_hours: number;
  readonly time_range: FgTimeRange;
  readonly timestamps: readonly string[];
}

export interface FgSolarIrradiance {
  readonly clear_sky: {
    readonly ghi: number;
    readonly dni: number;
    readonly dhi: number;
  };
  readonly description: string;
}

export interface FgEnvLocation {
  readonly lat: number;
  readonly lon: number;
  readonly elevation: number | null;
  readonly temperature: number;
  readonly parameters: Readonly<Partial<Record<FgEnvParameterName, FgParameterSeries>>>;
  readonly solar_irradiance?: FgSolarIrradiance;
}

export interface FgEnvParamsResult {
  readonly metadata: FgEnvMetadata;
  readonly locations: readonly FgEnvLocation[];
}

/* ─────────────────────────────────────────────────────────────────────────────
 * Envelope
 * ────────────────────────────────────────────────────────────────────────────*/

/** Submission response — returns an activity handle, not a result. */
export interface FgSubmitEnvelope {
  readonly error: boolean;
  readonly status_code: number;
  readonly message: string;
  readonly data: { readonly activity_id: string };
}

/** Status-poll response. `result` is present only when Completed. */
export interface FgStatusEnvelope<TResult> {
  readonly error: boolean;
  readonly status_code: number;
  readonly message: string;
  readonly data: {
    readonly activity_id: string;
    readonly status: FgActivityStatus;
    readonly result?: TResult;
  };
}

export type FgHeatmapStatus = FgStatusEnvelope<FgHeatmapResult>;
export type FgEnvParamsStatus = FgStatusEnvelope<FgEnvParamsResult>;

/**
 * Sentinel used by older stored FortyGuard records for a missing value.
 * Treated as missing, never as zero.
 */
export const FG_LEGACY_MISSING = -999;


/** Shorthand → the documented key, matching the backend's STAT_NAMES. */
const STAT_KEYS: Readonly<Record<string, string>> = {
  min: 'Minimum',
  max: 'Maximum',
  mean: 'Mean',
  std: 'Standard_deviation',
};

/**
 * One statistic from `stats_data`, under whichever casing it arrived in.
 *
 * The exact counterpart of `read_stat` in `clients/fortyguard/parsing.py`: the
 * block may be `Temperature_stats` or `temperature_stats`, and the field may be
 * `Maximum` or `maximum`. Both spellings name the same measurement, so reading
 * either is not a guess.
 *
 * Returns null when absent. Null renders as an explicit no-data cell; zero would
 * render as a measurement, and a mean of 0 °C would make every tile look
 * extraordinarily hot.
 */
export function fgStat(
  stats: FgStatsData | null | undefined,
  name: 'min' | 'max' | 'mean' | 'std',
): number | null {
  const block = fgStatsBlock<Record<string, unknown>>(stats, 'Temperature_stats');
  if (block === null) return null;
  const documented = STAT_KEYS[name] ?? name;
  const raw = block[documented] ?? block[documented.toLowerCase()];
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : null;
}


/**
 * The backend's flattened statistics block, as `/stats` returns it.
 *
 * Distinct from `FgStatsData`, which is the API's raw `stats_data` and is what
 * the committed fixtures carry. The backend reads the raw blob through
 * `read_stat` and publishes this; both describe the same measurement.
 *
 * Every field is nullable, and that is load-bearing rather than defensive: the
 * live API sends no `units` for `tcm`, so a non-null default here would be a
 * fabricated unit label on every temperature in the product.
 */
export interface FgStatsFlat {
  readonly min: number | null;
  readonly max: number | null;
  readonly mean: number | null;
  readonly median: number | null;
  readonly std: number | null;
  readonly count: number | null;
  readonly units: string | null;
}
