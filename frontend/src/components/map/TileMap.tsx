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
  type MapLayerMouseEvent,
  type StyleSpecification,
} from 'maplibre-gl';
import { useEffect, useRef } from 'react';

import { BRAND, MAP, MAP_DEFAULTS } from '@/constants';
import { heatPaintExpression } from '@/lib/scale';
import { cn } from '@/lib/cn';
import type { TileCollection } from '@/types';

/**
 * Point MapLibre at the worker bundle copied into `public/` by
 * `scripts/copy-maplibre-worker.mjs`.
 *
 * Without this, Turbopack fails to resolve the worker's module URL, the server
 * returns its HTML 404 page, and MapLibre SILENTLY falls back to parsing tiles
 * on the main thread — the map renders, so nothing looks wrong, but tile parsing
 * blocks the UI thread at the scale this product operates at (SRS §21.2).
 *
 * Called at module scope because it must run before any Map is constructed.
 */
setWorkerUrl('/maplibre-gl-worker.mjs');

const SOURCE_ID = 'coolrx-tiles';
const FILL_LAYER_ID = 'coolrx-tiles-fill';
const OUTLINE_LAYER_ID = 'coolrx-tiles-outline';
const SELECTION_LAYER_ID = 'coolrx-tiles-selection';

/**
 * Minimal self-contained style.
 *
 * Deliberately carries NO external tile source. A hosted basemap would add a
 * network dependency to the single most important screen in the demo, and at
 * district zoom the data layer carries the meaning anyway. Set
 * `NEXT_PUBLIC_MAP_STYLE_URL` to layer a real basemap underneath when street
 * context is wanted; the data layers are unaffected either way.
 */
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
}

type TileGeoJson = FeatureCollection<Polygon, TileProperties>;

/**
 * Convert the domain's `readonly` GeoJSON into the mutable shape MapLibre's
 * types require.
 *
 * The domain types are deliberately `readonly` so nothing downstream can mutate
 * a measurement in place. MapLibre types its GeoJSON as mutable, so the boundary
 * needs one explicit copy rather than a cast that lies about immutability.
 */
function toMapLibreGeoJson(tiles: TileCollection): TileGeoJson {
  return {
    type: 'FeatureCollection',
    features: tiles.features.map((feature) => ({
      type: 'Feature',
      properties: {
        tile_key: feature.properties.tile_key,
        value: feature.properties.value,
      },
      geometry: {
        type: 'Polygon',
        coordinates: feature.geometry.coordinates.map((ring) =>
          ring.map(([lon, lat]) => [lon, lat]),
        ),
      },
    })),
  };
}

interface TileMapProps {
  readonly tiles: TileCollection;
  /** Value domain for the colour ramp. */
  readonly domain: readonly [number, number];
  readonly selectedTileKey: string | null;
  readonly onSelectTile: (tileKey: string) => void;
  /** Initial view. */
  readonly center: readonly [number, number];
  readonly zoom?: number;
  readonly className?: string;
}

export function TileMap({
  tiles,
  domain,
  selectedTileKey,
  onSelectTile,
  center,
  zoom = 13,
  className,
}: TileMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  // Held in a ref so the click handler is registered once but always sees the
  // current callback. Refreshed in an effect rather than during render: a ref is
  // not a render input, so writing one while rendering makes the result depend
  // on how many times React evaluates the component.
  const onSelectRef = useRef(onSelectTile);
  useEffect(() => {
    onSelectRef.current = onSelectTile;
  }, [onSelectTile]);

  /* ── Initialise once ───────────────────────────────────────────────────── */
  useEffect(() => {
    const container = containerRef.current;
    if (container === null || mapRef.current !== null) return;

    const styleUrl = process.env.NEXT_PUBLIC_MAP_STYLE_URL;
    const map = new MapLibreMap({
      container,
      style: styleUrl !== undefined && styleUrl !== '' ? styleUrl : BASE_STYLE,
      center: [center[0], center[1]],
      zoom,
      attributionControl: false,
      // Pitch/rotate add nothing to a choropleth and make comparison harder.
      pitchWithRotate: false,
      dragRotate: false,
    });

    map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    map.addControl(
      new AttributionControl({
        compact: true,
        customAttribution: BRAND.attribution,
      }),
      'bottom-left',
    );

    map.on('load', () => {
      map.addSource(SOURCE_ID, {
        type: 'geojson',
        data: toMapLibreGeoJson(tiles),
      });

      map.addLayer({
        id: FILL_LAYER_ID,
        type: 'fill',
        source: SOURCE_ID,
        paint: {
          'fill-color': heatPaintExpression('value', domain),
          'fill-opacity': MAP_DEFAULTS.tileOpacity,
        },
      });

      // Tile borders only at high zoom — outlining thousands of tiles at
      // district zoom produces moiré (SRS §28.8).
      map.addLayer({
        id: OUTLINE_LAYER_ID,
        type: 'line',
        source: SOURCE_ID,
        minzoom: MAP_DEFAULTS.tileBorderMinZoom,
        paint: {
          'line-color': MAP.street,
          'line-width': 0.5,
        },
      });

      // Selection is an OUTLINE, never a fill change — recolouring the selected
      // tile would corrupt the value encoding.
      map.addLayer({
        id: SELECTION_LAYER_ID,
        type: 'line',
        source: SOURCE_ID,
        paint: {
          'line-color': MAP.selectionOutline,
          'line-width': MAP_DEFAULTS.selectionOutlineWidth,
        },
        filter: ['==', ['get', 'tile_key'], ''],
      });

      map.on('click', FILL_LAYER_ID, (event: MapLayerMouseEvent) => {
        const feature = event.features?.[0];
        const key = feature?.properties?.['tile_key'];
        if (typeof key === 'string') onSelectRef.current(key);
      });

      map.on('mouseenter', FILL_LAYER_ID, () => {
        map.getCanvas().style.cursor = 'pointer';
      });
      map.on('mouseleave', FILL_LAYER_ID, () => {
        map.getCanvas().style.cursor = '';
      });
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // Initialisation only — subsequent prop changes are handled by the effects
    // below so the map is never torn down and rebuilt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── Update data and ramp when the analytic layer changes ──────────────── */
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !map.isStyleLoaded()) return;

    const source = map.getSource<GeoJSONSource>(SOURCE_ID);
    if (source !== undefined) {
      source.setData(toMapLibreGeoJson(tiles));
    }

    if (map.getLayer(FILL_LAYER_ID) !== undefined) {
      map.setPaintProperty(
        FILL_LAYER_ID,
        'fill-color',
        heatPaintExpression('value', domain),
      );
    }
  }, [tiles, domain]);

  /* ── Update the selection outline ──────────────────────────────────────── */
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || map.getLayer(SELECTION_LAYER_ID) === undefined) return;

    const filter: FilterSpecification = [
      '==',
      ['get', 'tile_key'],
      selectedTileKey ?? '',
    ];
    map.setFilter(SELECTION_LAYER_ID, filter);
  }, [selectedTileKey]);

  return (
    <div
      ref={containerRef}
      className={cn('size-full', className)}
      role="application"
      aria-label="District temperature map. The ranked block table below conveys the same data."
    />
  );
}
