'use client';

import 'maplibre-gl/dist/maplibre-gl.css';

import type { FeatureCollection, Polygon } from 'geojson';
import {
  AttributionControl,
  Map as MapLibreMap,
  NavigationControl,
  setWorkerUrl,
  type FilterSpecification,
  type GeoJSONSource,
  type StyleSpecification,
} from 'maplibre-gl';
import { useCallback, useEffect, useRef } from 'react';

import { BRAND, MAP_DEFAULTS } from '@/constants';
import { heatPaintExpression } from '@/lib/scale';
import { cn } from '@/lib/cn';
import type { TileCollection } from '@/types';

setWorkerUrl('/maplibre-gl-worker.mjs');

const BEFORE_SOURCE = 'swipe-before';
const AFTER_SOURCE = 'swipe-after';
const BEFORE_LAYER = 'swipe-before-fill';
const AFTER_LAYER = 'swipe-after-fill';

const BASE_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [
    {
      id: 'background',
      type: 'background',
      paint: { 'background-color': '#eceae5' },
    },
  ],
};

interface TileProperties {
  tile_key: string;
  value: number | null;
  /** Tile centroid longitude — drives the swipe clip. */
  cx: number;
}

type SwipeGeoJson = FeatureCollection<Polygon, TileProperties>;

function toGeoJson(tiles: TileCollection): SwipeGeoJson {
  return {
    type: 'FeatureCollection',
    features: tiles.features.map((feature) => {
      const ring = feature.geometry.coordinates[0] ?? [];
      const lons = ring.map(([lon]) => lon);
      const cx =
        lons.length === 0
          ? 0
          : lons.reduce((sum, lon) => sum + lon, 0) / lons.length;

      return {
        type: 'Feature' as const,
        properties: {
          tile_key: feature.properties.tileKey,
          value: feature.properties.value,
          cx,
        },
        geometry: {
          type: 'Polygon' as const,
          coordinates: feature.geometry.coordinates.map((r) =>
            r.map(([lon, lat]) => [lon, lat]),
          ),
        },
      };
    }),
  };
}

interface SwipeCompareMapProps {
  readonly before: TileCollection;
  readonly after: TileCollection;
  /**
   * ⚠️ ONE domain, used by BOTH layers.
   *
   * SRS §28.8: a different colour scale on each side of the divider would be a
   * visual lie — the whole point of the comparison is that identical colours
   * mean identical temperatures. The prop is deliberately singular so a caller
   * cannot pass two.
   */
  readonly sharedDomain: readonly [number, number];
  /** Divider position as a fraction of container width, 0–1. */
  readonly position: number;
  readonly onPositionChange: (position: number) => void;
  readonly center: readonly [number, number];
  readonly zoom?: number;
  readonly className?: string;
}

/**
 * Before/After swipe comparison.
 *
 * Implemented as ONE map with two fill layers, where the "after" layer is
 * filtered to tiles east of the divider's longitude. The obvious alternative —
 * two stacked maps with CSS clip-path — needs two WebGL contexts, two tile
 * parses and continuous camera synchronisation. A geographic filter costs one
 * `setFilter` per drag frame instead.
 */
export function SwipeCompareMap({
  before,
  after,
  sharedDomain,
  position,
  onPositionChange,
  center,
  zoom = 13,
  className,
}: SwipeCompareMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const draggingRef = useRef(false);
  const positionRef = useRef(position);
  // Reconciles the optimistic writes in `commitPosition` back to the prop. This
  // effect must stay declared above the one that calls `applyClip`, because
  // effects run in declaration order and `applyClip` reads `positionRef.current`
  // — reversing them would clip against the previous position for one frame.
  useEffect(() => {
    positionRef.current = position;
  }, [position]);

  /** Translate the divider's screen fraction into a longitude and re-filter. */
  const applyClip = useCallback(() => {
    const map = mapRef.current;
    const container = containerRef.current;
    if (map === null || container === null) return;
    if (map.getLayer(AFTER_LAYER) === undefined) return;

    const width = container.clientWidth;
    const x = width * positionRef.current;
    const { lng } = map.unproject([x, container.clientHeight / 2]);

    const filter: FilterSpecification = ['>=', ['get', 'cx'], lng];
    map.setFilter(AFTER_LAYER, filter);
  }, []);

  /* ── Initialise ────────────────────────────────────────────────────────── */
  useEffect(() => {
    const container = containerRef.current;
    if (container === null || mapRef.current !== null) return;

    const map = new MapLibreMap({
      container,
      style: BASE_STYLE,
      center: [center[0], center[1]],
      zoom,
      attributionControl: false,
      pitchWithRotate: false,
      dragRotate: false,
    });

    map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    map.addControl(
      new AttributionControl({ compact: true, customAttribution: BRAND.attribution }),
      'bottom-left',
    );

    map.on('load', () => {
      map.addSource(BEFORE_SOURCE, { type: 'geojson', data: toGeoJson(before) });
      map.addSource(AFTER_SOURCE, { type: 'geojson', data: toGeoJson(after) });

      // Both layers share ONE paint expression built from ONE domain.
      const paint = heatPaintExpression('value', sharedDomain);

      map.addLayer({
        id: BEFORE_LAYER,
        type: 'fill',
        source: BEFORE_SOURCE,
        paint: { 'fill-color': paint, 'fill-opacity': MAP_DEFAULTS.tileOpacity },
      });

      map.addLayer({
        id: AFTER_LAYER,
        type: 'fill',
        source: AFTER_SOURCE,
        paint: { 'fill-color': paint, 'fill-opacity': MAP_DEFAULTS.tileOpacity },
      });

      applyClip();
    });

    // The clip is defined in screen space, so it must follow the camera.
    map.on('move', applyClip);
    map.on('resize', applyClip);

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── Re-apply when data, domain or divider changes ─────────────────────── */
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !map.isStyleLoaded()) return;

    map.getSource<GeoJSONSource>(BEFORE_SOURCE)?.setData(toGeoJson(before));
    map.getSource<GeoJSONSource>(AFTER_SOURCE)?.setData(toGeoJson(after));

    const paint = heatPaintExpression('value', sharedDomain);
    for (const layer of [BEFORE_LAYER, AFTER_LAYER]) {
      if (map.getLayer(layer) !== undefined) {
        map.setPaintProperty(layer, 'fill-color', paint);
      }
    }
    applyClip();
  }, [before, after, sharedDomain, applyClip]);

  useEffect(() => {
    applyClip();
  }, [position, applyClip]);

  /* ── Divider interaction ───────────────────────────────────────────────── */

  /**
   * Emit a new position and optimistically advance the ref.
   *
   * `positionRef` is only refreshed once the store round-trip lands, so without
   * the local write a burst of keydowns faster than React can re-render would
   * all read the same stale value and collapse into a single step — exactly what
   * happens when a user holds an arrow key down. Writing here makes repeats
   * accumulate; the effect above still reconciles it with the store.
   */
  const commitPosition = useCallback(
    (next: number) => {
      const clamped = Math.min(1, Math.max(0, next));
      positionRef.current = clamped;
      onPositionChange(clamped);
    },
    [onPositionChange],
  );

  const updateFromClientX = useCallback(
    (clientX: number) => {
      const container = containerRef.current;
      if (container === null) return;
      const rect = container.getBoundingClientRect();
      // Absolute from pointer position, so no accumulation concern here.
      commitPosition((clientX - rect.left) / rect.width);
    },
    [commitPosition],
  );

  useEffect(() => {
    const onMove = (event: PointerEvent) => {
      if (!draggingRef.current) return;
      event.preventDefault();
      updateFromClientX(event.clientX);
    };
    const onUp = () => {
      draggingRef.current = false;
    };

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [updateFromClientX]);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const step = event.shiftKey ? 0.1 : 0.02;
      switch (event.key) {
        case 'ArrowLeft':
          event.preventDefault();
          commitPosition(positionRef.current - step);
          break;
        case 'ArrowRight':
          event.preventDefault();
          commitPosition(positionRef.current + step);
          break;
        case 'Home':
          event.preventDefault();
          commitPosition(0);
          break;
        case 'End':
          event.preventDefault();
          commitPosition(1);
          break;
        default:
          break;
      }
    },
    [commitPosition],
  );

  return (
    <div className={cn('relative size-full', className)}>
      <div ref={containerRef} className="size-full" />

      {/* Side labels */}
      <span className="pointer-events-none absolute left-4 top-4 rounded-sharp border border-line bg-card/95 px-2 py-1 text-eyebrow uppercase tracking-[0.08em] text-ink-secondary">
        Now
      </span>
      <span className="pointer-events-none absolute right-4 top-4 rounded-sharp border border-line bg-card/95 px-2 py-1 text-eyebrow uppercase tracking-[0.08em] text-accent">
        Predicted
      </span>

      {/* Divider — keyboard operable (SRS §15.7) */}
      <div
        role="slider"
        tabIndex={0}
        aria-label="Comparison divider. Left of it shows current conditions, right shows predicted."
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(position * 100)}
        aria-valuetext={`${Math.round(position * 100)}% predicted`}
        onKeyDown={onKeyDown}
        onPointerDown={(event) => {
          draggingRef.current = true;
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        className="absolute inset-y-0 z-10 w-1 -translate-x-1/2 cursor-col-resize bg-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        style={{ left: `${position * 100}%` }}
      >
        <span
          aria-hidden
          className="absolute left-1/2 top-1/2 flex size-8 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-sharp border border-ink bg-card text-ink"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
            <path
              d="M5 3L2 7l3 4M9 3l3 4-3 4"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      </div>
    </div>
  );
}
