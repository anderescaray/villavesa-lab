/**
 * Accessibility choropleth (MapLibre). The 200 m zone cells are drawn twice (slots a/b) from the
 * same static geometry; colours live in feature-state, so a new metric/threshold/window only
 * writes 1 794 states into the idle slot and crossfades the two layers (200 ms). The previous
 * map stays visible (dimmed) while the next window computes. POIs of the selected category sit
 * above the network; hovering a cell or a POI shows a tooltip.
 */
import type { Map as MlMap, MapMouseEvent } from 'maplibre-gl';
import { useEffect, useRef, useState } from 'react';
import { usePois, useZones } from '@/api/queries';
import type { Accessibility, ZonesGeoJSON } from '@/api/types';
import { useApp, type Theme } from '@/app/store';
import { clockActions } from '@/features/time/clock';
import { ROUTE_LAYERS } from '@/features/network/NetworkLayers';
import { useMapContext } from '@/map/MapContext';
import { ensureLayer, setFilter, setGeoJSON, setPaint } from '@/map/maplibreLayers';
import { CellTooltip, PoiTooltip } from './MapTooltip';
import { zoneColors } from './model';
import { useAccessibility } from './useAccessibility';

type Slot = 'a' | 'b';
const SLOTS: Slot[] = ['a', 'b'];
const srcId = (s: Slot) => `vl-acc-${s}`;
const fillId = (s: Slot) => `vl-acc-fill-${s}`;
const HOVER_LINE = 'vl-acc-hover';
const POI_SOURCE = 'vl-acc-pois';
const POI_LAYER = 'vl-acc-pois';
const FADE = { duration: 200, delay: 0 };
const STALE_OPACITY = 0.45;

export interface CellHover {
  zone: number;
  x: number;
  y: number;
}
export interface PoiHover {
  name: string;
  x: number;
  y: number;
}

function addLayers(map: MlMap, zones: ZonesGeoJSON, theme: Theme, anchor: string | undefined) {
  const below = map.getLayer(ROUTE_LAYERS.casing) ? ROUTE_LAYERS.casing : anchor;
  for (const slot of SLOTS) {
    setGeoJSON(map, srcId(slot), zones);
    ensureLayer(
      map,
      {
        id: fillId(slot),
        type: 'fill',
        source: srcId(slot),
        paint: {
          'fill-color': ['to-color', ['coalesce', ['feature-state', 'c'], 'rgba(0,0,0,0)']],
          'fill-opacity': 0,
          'fill-opacity-transition': FADE,
          'fill-antialias': false,
        },
      },
      below,
    );
  }
  ensureLayer(
    map,
    {
      id: HOVER_LINE,
      type: 'line',
      source: srcId('a'),
      paint: {
        'line-color': theme === 'dark' ? '#eceef1' : '#0f1216',
        'line-width': 1.5,
        'line-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.9, 0],
      },
    },
    below,
  );
  ensureLayer(
    map,
    {
      id: POI_LAYER,
      type: 'circle',
      source: POI_SOURCE,
      filter: ['==', ['get', 'category'], '__none__'],
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 3, 14, 4.5, 17, 6],
        'circle-color': theme === 'dark' ? '#eceef1' : '#0f1216',
        'circle-stroke-color': theme === 'dark' ? '#0b0c0e' : '#ffffff',
        'circle-stroke-width': 1.5,
      },
    },
    anchor,
  );
}

/** Keep the fills under the network and the POIs above it, whatever mounted first. */
function order(map: MlMap, anchor: string | undefined) {
  if (map.getLayer(ROUTE_LAYERS.casing)) {
    for (const id of [fillId('a'), fillId('b'), HOVER_LINE])
      if (map.getLayer(id)) map.moveLayer(id, ROUTE_LAYERS.casing);
  }
  if (map.getLayer(POI_LAYER)) map.moveLayer(POI_LAYER, anchor && map.getLayer(anchor) ? anchor : undefined);
}

function writeColors(map: MlMap, slot: Slot, colors: string[]) {
  const source = srcId(slot);
  if (!map.getSource(source)) return;
  for (let i = 0; i < colors.length; i++) map.setFeatureState({ source, id: i }, { c: colors[i] });
}

export function AccessibilityLayers() {
  const { map, styleVersion, anchor } = useMapContext();
  const view = useApp((s) => s.view);
  const active = view === 'accessibility';
  const theme = useApp((s) => s.theme);
  const metric = useApp((s) => s.accMetric);
  const category = useApp((s) => s.accCategory);
  const { data, stale } = useAccessibility();
  const { data: zones } = useZones(active);
  const { data: pois } = usePois(active);
  const slot = useRef<Slot>('a');
  const shown = useRef<string>('');
  const [cell, setCell] = useState<CellHover | null>(null);
  const [poi, setPoi] = useState<PoiHover | null>(null);
  const hoverId = useRef<number | null>(null);

  // the analysis window follows the clock: stop the animation in this view
  useEffect(() => {
    if (active) clockActions.pause();
  }, [active]);

  // sources + layers after each style load
  useEffect(() => {
    if (!map || !styleVersion || !zones) return;
    if (pois) setGeoJSON(map, POI_SOURCE, poisGeoJSON(pois.pois));
    else setGeoJSON(map, POI_SOURCE, { type: 'FeatureCollection', features: [] });
    addLayers(map, zones, theme, anchor);
    order(map, anchor);
    shown.current = ''; // feature-state is lost with the style: repaint
  }, [map, styleVersion, zones, pois, theme, anchor]);

  // colours → idle slot, then crossfade
  useEffect(() => {
    if (!map || !styleVersion || !zones) return;
    order(map, anchor);
    if (!active || !data) {
      for (const s of SLOTS) setPaint(map, fillId(s), 'fill-opacity', 0);
      setFilter(map, POI_LAYER, ['==', ['get', 'category'], '__none__']);
      shown.current = '';
      return;
    }
    setFilter(map, POI_LAYER, ['==', ['get', 'category'], category]);
    const key = `${data.window.day}|${data.window.start}|${data.threshold}|${metric}|${category}|${theme}`;
    const level = stale ? STALE_OPACITY : 1;
    if (key === shown.current) {
      setPaint(map, fillId(slot.current), 'fill-opacity', level);
      return;
    }
    const first = shown.current === '';
    const next: Slot = first ? slot.current : slot.current === 'a' ? 'b' : 'a';
    const prev = slot.current;
    writeColors(map, next, zoneColors(data, metric, category, theme));
    if (!first) map.moveLayer(fillId(prev), fillId(next)); // old below new while fading
    setPaint(map, fillId(next), 'fill-opacity', level);
    const id = window.setTimeout(() => {
      if (next !== prev) setPaint(map, fillId(prev), 'fill-opacity', 0);
    }, FADE.duration + 40);
    slot.current = next;
    shown.current = key;
    return () => window.clearTimeout(id);
  }, [map, styleVersion, zones, data, stale, metric, category, theme, active, anchor]);

  // hover: cell tooltip + outline, POI names
  useEffect(() => {
    if (!map || !active || !zones) return;
    let raf = 0;
    let pending: MapMouseEvent | null = null;
    const setHover = (id: number | null) => {
      if (hoverId.current === id) return;
      if (hoverId.current !== null && map.getSource(srcId('a')))
        map.setFeatureState({ source: srcId('a'), id: hoverId.current }, { hover: false });
      if (id !== null && map.getSource(srcId('a')))
        map.setFeatureState({ source: srcId('a'), id }, { hover: true });
      hoverId.current = id;
    };
    const evaluate = () => {
      raf = 0;
      const e = pending;
      if (!e) return;
      const { x, y } = e.point;
      const p = map.getLayer(POI_LAYER)
        ? map.queryRenderedFeatures(
            [
              [x - 5, y - 5],
              [x + 5, y + 5],
            ],
            { layers: [POI_LAYER] },
          )[0]
        : undefined;
      if (p) {
        setHover(null);
        setCell(null);
        setPoi({ name: String(p.properties?.name ?? ''), x, y });
        map.getCanvas().style.cursor = 'default';
        return;
      }
      setPoi(null);
      const layer = fillId(slot.current);
      const f = map.getLayer(layer) ? map.queryRenderedFeatures([x, y], { layers: [layer] })[0] : undefined;
      const id = typeof f?.id === 'number' ? f.id : null;
      const pop = id !== null ? (zones.features[id]?.properties.population ?? 0) : 0;
      if (id === null || pop <= 0) {
        setHover(null);
        setCell(null);
        return;
      }
      setHover(id);
      setCell({ zone: id, x, y });
    };
    const onMove = (e: MapMouseEvent) => {
      pending = e;
      if (!raf) raf = requestAnimationFrame(evaluate);
    };
    const onLeave = () => {
      pending = null;
      setHover(null);
      setCell(null);
      setPoi(null);
    };
    map.getCanvas().style.cursor = 'default';
    map.on('mousemove', onMove);
    map.on('mouseout', onLeave);
    return () => {
      cancelAnimationFrame(raf);
      onLeave();
      map.getCanvas().style.cursor = '';
      map.off('mousemove', onMove);
      map.off('mouseout', onLeave);
    };
  }, [map, active, zones, styleVersion]);

  if (!active) return null;
  return (
    <>
      {cell && data ? <CellTooltip hover={cell} data={data as Accessibility} zones={zones} /> : null}
      {poi ? <PoiTooltip hover={poi} /> : null}
    </>
  );
}

function poisGeoJSON(
  pois: { id: number; category: string; name: string; lon: number; lat: number }[],
): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: pois.map((p) => ({
      type: 'Feature' as const,
      properties: { category: p.category, name: p.name },
      geometry: { type: 'Point' as const, coordinates: [p.lon, p.lat] },
    })),
  };
}
