/**
 * Client-side AOI geometry and pre-validation.
 *
 * This mirrors `backend/clients/fortyguard/validation.py` so the AOI Studio can
 * respond to every drag of the size slider without a round-trip. It is
 * deliberately **not authoritative** — the server re-validates with pyproj on the
 * WGS84 ellipsoid before anything is persisted or submitted, and its answer wins.
 *
 * The two differ by well under a percent: the server uses the ellipsoid, this uses
 * a spherical approximation on the authalic radius. That gap is why the Studio
 * shows a live local estimate while dragging and then reconciles against the
 * server's number once the slider settles, rather than pretending the local figure
 * is final. Near the cap the difference could flip a verdict, so the UI never says
 * "valid" on the strength of this alone.
 */

import { FG_LIMITS } from '@/constants';

/** Earth's authalic (equal-area) radius, metres. The right radius for areas. */
const AUTHALIC_RADIUS_M = 6_371_007.181;

const SQ_METRES_PER_SQ_MILE = 2_589_988.110336;

const toRadians = (degrees: number): number => (degrees * Math.PI) / 180;

export interface BoundingBox {
  readonly west: number;
  readonly south: number;
  readonly east: number;
  readonly north: number;
}

/**
 * Geodesic area of a lat/lon rectangle, in square miles.
 *
 * Uses the exact spherical formula `R² · Δλ · (sin φ₂ − sin φ₁)` rather than
 * multiplying a width by a height. The naive version treats a degree of longitude
 * as a fixed distance and overstates area at high latitude — by about 20% in
 * Anchorage, which would let a non-compliant AOI through the local check.
 */
export function areaSqMi(box: BoundingBox): number {
  const deltaLon = toRadians(Math.abs(box.east - box.west));
  const sinDelta =
    Math.sin(toRadians(box.north)) - Math.sin(toRadians(box.south));
  const areaM2 = AUTHALIC_RADIUS_M ** 2 * deltaLon * Math.abs(sinDelta);
  return areaM2 / SQ_METRES_PER_SQ_MILE;
}

/**
 * A square-ish box of a given edge length around a centre point.
 *
 * The longitude span is divided by `cos(latitude)` so the box is square *on the
 * ground* rather than in degrees. Without that correction a "2 km" box in Phoenix
 * would be 2 km tall and 1.7 km wide.
 */
export function boxAround(
  centerLon: number,
  centerLat: number,
  edgeKm: number,
): BoundingBox {
  const halfLat = edgeKm / 2 / 110.574;
  const cos = Math.cos(toRadians(centerLat));
  // Guard the pole: cos → 0 makes the longitude span diverge.
  const halfLon = edgeKm / 2 / (111.32 * Math.max(cos, 0.01));

  return {
    west: centerLon - halfLon,
    south: centerLat - halfLat,
    east: centerLon + halfLon,
    north: centerLat + halfLat,
  };
}

/** GeoJSON FeatureCollection for a box, in the shape the API expects. */
export function boxToFeatureCollection(box: BoundingBox): {
  readonly type: 'FeatureCollection';
  readonly features: readonly {
    readonly type: 'Feature';
    readonly properties: Record<string, never>;
    readonly geometry: {
      readonly type: 'Polygon';
      readonly coordinates: readonly (readonly (readonly [number, number])[])[];
    };
  }[];
} {
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'Polygon',
          // Closed ring: the first position is repeated last, as GeoJSON requires.
          coordinates: [
            [
              [box.west, box.south],
              [box.east, box.south],
              [box.east, box.north],
              [box.west, box.north],
              [box.west, box.south],
            ],
          ],
        },
      },
    ],
  };
}

/**
 * US coverage rectangles, mirroring `US_REGION_BOXES` on the server.
 *
 * Three boxes rather than one: a single generous rectangle spanning CONUS, Alaska
 * and Hawaii also admits most of Canada and Mexico, and each of those would spend
 * a credit to return nothing.
 */
const US_REGION_BOXES: readonly BoundingBox[] = [
  { west: -125.0, south: 24.4, east: -66.9, north: 49.05 }, // CONUS
  { west: -172.5, south: 51.0, east: -129.0, north: 71.5 }, // Alaska
  { west: -160.6, south: 18.8, east: -154.7, north: 22.3 }, // Hawaii
];

/**
 * Whether a point is inside the US coverage pre-filter.
 *
 * A *pre-filter*, not a border test. Toronto sits south of the 49th parallel
 * between the same meridians as Buffalo, so no rectangle can separate them; the
 * server carries the same documented limitation and a test asserting it.
 */
export function inUsCoverage(lon: number, lat: number): boolean {
  return US_REGION_BOXES.some(
    (box) =>
      lon >= box.west && lon <= box.east && lat >= box.south && lat <= box.north,
  );
}

export type AoiIssueCode =
  | 'AOI_AREA_EXCEEDED'
  | 'AOI_OUTSIDE_COVERAGE'
  | 'DATE_BELOW_FLOOR'
  | 'DATE_BEYOND_FORECAST';

export interface AoiIssue {
  readonly code: AoiIssueCode;
  readonly message: string;
  readonly field: string;
}

/** Local pre-flight. Instant feedback; the server still decides. */
export function preflight(params: {
  readonly box: BoundingBox;
  readonly startDate: string;
  readonly maxAreaSqMi?: number;
  readonly now?: Date;
}): readonly AoiIssue[] {
  const { box, startDate } = params;
  const cap = params.maxAreaSqMi ?? FG_LIMITS.maxAoiSqMi;
  const now = params.now ?? new Date();
  const issues: AoiIssue[] = [];

  const area = areaSqMi(box);
  if (area > cap) {
    issues.push({
      code: 'AOI_AREA_EXCEEDED',
      message: `This area is ${area.toFixed(2)} mi², above the ${cap} mi² limit for our API plan.`,
      field: 'aoi',
    });
  }

  const centerLon = (box.west + box.east) / 2;
  const centerLat = (box.south + box.north) / 2;
  if (!inUsCoverage(centerLon, centerLat)) {
    issues.push({
      code: 'AOI_OUTSIDE_COVERAGE',
      message: 'Temperature coverage is United States only.',
      field: 'aoi',
    });
  }

  const parsed = new Date(`${startDate}T00:00:00Z`);
  const floor = new Date(`${FG_LIMITS.dateFloor}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) {
    issues.push({
      code: 'DATE_BELOW_FLOOR',
      message: 'Pick a valid date.',
      field: 'startDate',
    });
  } else {
    if (parsed < floor) {
      issues.push({
        code: 'DATE_BELOW_FLOOR',
        message: `History starts at ${FG_LIMITS.dateFloor}.`,
        field: 'startDate',
      });
    }
    const horizon = new Date(
      now.getTime() + FG_LIMITS.maxForecastHours * 3_600_000,
    );
    if (parsed > horizon) {
      issues.push({
        code: 'DATE_BEYOND_FORECAST',
        message: `Forecasts reach only ${FG_LIMITS.maxForecastHours} hours ahead.`,
        field: 'startDate',
      });
    }
  }

  return issues;
}

/**
 * Tiles a run will produce, for the cost preview.
 *
 * Approximate by design — the server builds the real grid in UTM. It is shown
 * rounded and labelled "about" so the figure is never read as exact.
 */
export function estimateTileCount(box: BoundingBox, granularityM: number): number {
  const areaM2 = areaSqMi(box) * SQ_METRES_PER_SQ_MILE;
  return Math.round(areaM2 / granularityM ** 2);
}

/** Credits a diagnosis costs: 3 base analytics, plus 11 ladder rungs if built. */
export function estimateCredits(buildLadder: boolean): number {
  return 3 + (buildLadder ? FG_LIMITS.ladderSteps + 1 : 0);
}
