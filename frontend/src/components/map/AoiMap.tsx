'use client';

import 'maplibre-gl/dist/maplibre-gl.css';

import {
  AttributionControl,
  Map as MapLibreMap,
  NavigationControl,
  setWorkerUrl,
  type GeoJSONSource,
  type MapMouseEvent,
  type StyleSpecification,
} from 'maplibre-gl';
import { useEffect, useRef } from 'react';

import { BRAND, MAP } from '@/constants';
import { boxToFeatureCollection, type BoundingBox } from '@/lib/aoi';
import { cn } from '@/lib/cn';

// Same reason as TileMap: without this, Turbopack cannot resolve the worker URL,
// the server returns HTML, and MapLibre silently falls back to main-thread tile
// parsing. Must run before any Map is constructed.
setWorkerUrl('/maplibre-gl-worker.mjs');

const SOURCE_ID = 'coolrx-aoi';
const FILL_LAYER_ID = 'coolrx-aoi-fill';
const LINE_LAYER_ID = 'coolrx-aoi-line';

/** Self-contained, so the most important setup screen has no network dependency. */
const BASE_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [
    {
      id: 'background',
      type: 'background',
      paint: { 'background-color': MAP.background },
    },
  ],
  glyphs: undefined,
};

interface AoiMapProps {
  readonly box: BoundingBox;
  /** True when the box currently violates a limit — drawn in the danger colour. */
  readonly isInvalid: boolean;
  /** Clicking the map recentres the box there. */
  readonly onRecenter: (lon: number, lat: number) => void;
  readonly className?: string;
}

/**
 * Map for placing an area of interest.
 *
 * Deliberately click-to-place plus a size slider rather than draggable corner
 * handles. The API takes a bounding box of a capped area, so the only two degrees
 * of freedom that matter are where it sits and how big it is — corner handles
 * would let a user build a long thin sliver that satisfies the area cap while
 * being useless as a district, and they are far harder to use on a trackpad.
 *
 * The box turns red the moment it breaks a limit, so the constraint is visible
 * while dragging rather than only on submit.
 */
export function AoiMap({ box, isInvalid, onRecenter, className }: AoiMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  // Held in a ref so the click handler is registered once and never rebinds; a
  // handler recreated on every box change would leak listeners on each drag.
  // Refreshed in an effect rather than during render: a ref is not a render
  // input, so writing one while rendering makes the result depend on how many
  // times React evaluates the component.
  const onRecenterRef = useRef(onRecenter);
  useEffect(() => {
    onRecenterRef.current = onRecenter;
  }, [onRecenter]);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null || mapRef.current !== null) return undefined;

    const center = [
      (box.west + box.east) / 2,
      (box.south + box.north) / 2,
    ] as [number, number];

    const map = new MapLibreMap({
      container,
      style: BASE_STYLE,
      center,
      zoom: 11,
      attributionControl: false,
    });
    mapRef.current = map;

    map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    map.addControl(
      new AttributionControl({ compact: true, customAttribution: BRAND.attribution }),
      'bottom-right',
    );

    map.on('load', () => {
      map.addSource(SOURCE_ID, {
        type: 'geojson',
        data: boxToFeatureCollection(box) as never,
      });
      map.addLayer({
        id: FILL_LAYER_ID,
        type: 'fill',
        source: SOURCE_ID,
        paint: { 'fill-color': MAP.aoiFill, 'fill-opacity': 0.18 },
      });
      map.addLayer({
        id: LINE_LAYER_ID,
        type: 'line',
        source: SOURCE_ID,
        paint: { 'line-color': MAP.aoiLine, 'line-width': 2 },
      });
    });

    map.on('click', (event: MapMouseEvent) => {
      onRecenterRef.current(event.lngLat.lng, event.lngLat.lat);
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // Runs once. `box` is read for the initial centre only; later changes are
    // applied by the effect below without tearing down the map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Push box changes into the existing source rather than recreating it.
  useEffect(() => {
    const map = mapRef.current;
    if (map === null) return;

    const apply = (): void => {
      const source = map.getSource(SOURCE_ID) as GeoJSONSource | undefined;
      if (source === undefined) return;
      source.setData(boxToFeatureCollection(box) as never);

      if (map.getLayer(LINE_LAYER_ID)) {
        map.setPaintProperty(
          LINE_LAYER_ID,
          'line-color',
          isInvalid ? MAP.aoiInvalid : MAP.aoiLine,
        );
      }
      if (map.getLayer(FILL_LAYER_ID)) {
        map.setPaintProperty(
          FILL_LAYER_ID,
          'fill-color',
          isInvalid ? MAP.aoiInvalid : MAP.aoiFill,
        );
      }
    };

    if (map.isStyleLoaded()) apply();
    else map.once('load', apply);
  }, [box, isInvalid]);

  return (
    <div
      ref={containerRef}
      className={cn('size-full', className)}
      role="application"
      aria-label="Map for placing the analysis area. Click to move the area."
    />
  );
}
