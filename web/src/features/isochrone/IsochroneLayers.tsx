/**
 * Isochrone bands on the map (MapLibre fills + hairline outlines), drawn beneath the network.
 * Two slots (A/B) let a new result fade in band by band — smallest cutoff first — while the
 * previous one fades out, so moving the origin crossfades instead of popping.
 */
import maplibregl, { type Map as MlMap } from 'maplibre-gl';
import { useEffect, useRef } from 'react';
import type { IsochroneResponse } from '@/api/types';
import { useApp, type Theme } from '@/app/store';
import { ROUTE_LAYERS } from '@/features/network/NetworkLayers';
import { prefersReducedMotion } from '@/lib/motion';
import { ISO_COLORS, ISO_FILL_OPACITY } from '@/lib/palettes';
import { useMapContext } from '@/map/MapContext';
import { ensureLayer, setGeoJSON } from '@/map/maplibreLayers';
import { useIsochroneResult } from './useIsochroneRequest';
import s from './IsochronePin.module.css';

const SLOTS = ['a', 'b'] as const;
type Slot = (typeof SLOTS)[number];
const BANDS = [0, 1, 2] as const;
const src = (slot: Slot) => `vl-iso-${slot}`;
const fillId = (slot: Slot, k: number) => `vl-iso-${slot}-fill-${k}`;
const lineId = (slot: Slot, k: number) => `vl-iso-${slot}-line-${k}`;

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

function toGeoJSON(res: IsochroneResponse): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: res.isochrones.map((iso, k) => ({
      type: 'Feature',
      properties: { k, cutoff: iso.cutoff },
      geometry: iso.geometry as GeoJSON.MultiPolygon,
    })),
  };
}

function addSlot(map: MlMap, slot: Slot, theme: Theme) {
  setGeoJSON(map, src(slot), EMPTY);
  const before = map.getLayer(ROUTE_LAYERS.casing) ? ROUTE_LAYERS.casing : undefined;
  // largest band first so smaller ones stack on top
  for (const k of [...BANDS].reverse()) {
    ensureLayer(
      map,
      {
        id: fillId(slot, k),
        type: 'fill',
        source: src(slot),
        filter: ['==', ['get', 'k'], k],
        paint: { 'fill-color': ISO_COLORS[theme][k]!, 'fill-opacity': 0, 'fill-antialias': true },
      },
      before,
    );
  }
  for (const k of [...BANDS].reverse()) {
    ensureLayer(
      map,
      {
        id: lineId(slot, k),
        type: 'line',
        source: src(slot),
        filter: ['==', ['get', 'k'], k],
        layout: { 'line-join': 'round' },
        paint: {
          'line-color': ISO_COLORS[theme][k]!,
          'line-width': ['interpolate', ['linear'], ['zoom'], 10, 0.75, 15, 1.5],
          'line-opacity': 0,
        },
      },
      before,
    );
  }
}

function fade(map: MlMap, slot: Slot, theme: Theme, on: boolean, stagger: boolean) {
  const reduce = prefersReducedMotion();
  for (const k of BANDS) {
    const duration = reduce ? 0 : on ? 380 : 220;
    const delay = reduce || !on || !stagger ? 0 : k * 140;
    if (!map.getLayer(fillId(slot, k))) continue;
    map.setPaintProperty(fillId(slot, k), 'fill-opacity-transition', { duration, delay });
    map.setPaintProperty(lineId(slot, k), 'line-opacity-transition', { duration, delay });
    map.setPaintProperty(fillId(slot, k), 'fill-opacity', on ? ISO_FILL_OPACITY[theme][k]! : 0);
    map.setPaintProperty(lineId(slot, k), 'line-opacity', on ? 0.85 : 0);
  }
}

export function IsochroneLayers() {
  const { map, styleVersion } = useMapContext();
  const theme = useApp((st) => st.theme);
  const origin = useApp((st) =>
    st.view === 'accessibility' || st.view === 'scenario' ? null : st.isoOrigin,
  );
  const { data } = useIsochroneResult();
  const active = useRef<Slot>('a');
  const shown = useRef<IsochroneResponse | null>(null);

  // (re)create layers after each style load; re-apply the current result without animation
  useEffect(() => {
    if (!map || !styleVersion) return;
    for (const slot of SLOTS) addSlot(map, slot, theme);
    if (shown.current) {
      setGeoJSON(map, src(active.current), toGeoJSON(shown.current));
      fade(map, active.current, theme, true, false);
    }
  }, [map, styleVersion, theme]);

  // new result → crossfade into the idle slot
  useEffect(() => {
    if (!map || !styleVersion) return;
    if (!data || !origin) {
      if (shown.current) for (const slot of SLOTS) fade(map, slot, theme, false, false);
      shown.current = null;
      return;
    }
    if (data === shown.current) return;
    const next: Slot = shown.current ? (active.current === 'a' ? 'b' : 'a') : active.current;
    const prev = active.current;
    for (const k of BANDS) {
      if (!map.getLayer(fillId(next, k))) continue;
      map.setPaintProperty(fillId(next, k), 'fill-opacity-transition', { duration: 0, delay: 0 });
      map.setPaintProperty(fillId(next, k), 'fill-opacity', 0);
      map.setPaintProperty(lineId(next, k), 'line-opacity-transition', { duration: 0, delay: 0 });
      map.setPaintProperty(lineId(next, k), 'line-opacity', 0);
    }
    setGeoJSON(map, src(next), toGeoJSON(data));
    const raf = requestAnimationFrame(() => {
      if (next !== prev) fade(map, prev, theme, false, false);
      fade(map, next, theme, true, true);
    });
    active.current = next;
    shown.current = data;
    return () => cancelAnimationFrame(raf);
  }, [map, styleVersion, data, origin, theme]);

  return <IsochronePin />;
}

/** The origin pin: an HTML marker (crisp at any DPI, CSS-animated drop). */
function IsochronePin() {
  const { map } = useMapContext();
  const origin = useApp((st) =>
    st.view === 'accessibility' || st.view === 'scenario' ? null : st.isoOrigin,
  );
  const markerRef = useRef<maplibregl.Marker | null>(null);

  useEffect(() => {
    if (!map) return;
    if (!origin) {
      markerRef.current?.remove();
      markerRef.current = null;
      return;
    }
    if (!markerRef.current) {
      const el = document.createElement('div');
      el.className = s.pin ?? '';
      el.setAttribute('data-testid', 'iso-pin');
      el.innerHTML = `<span class="${s.pulse}"></span><span class="${s.dot}"></span>`;
      markerRef.current = new maplibregl.Marker({ element: el }).setLngLat(origin).addTo(map);
    } else {
      markerRef.current.setLngLat(origin);
      const el = markerRef.current.getElement();
      el.classList.remove(s.drop!);
      void el.offsetWidth; // restart the drop animation
      el.classList.add(s.drop!);
    }
  }, [map, origin]);

  useEffect(
    () => () => {
      markerRef.current?.remove();
      markerRef.current = null;
    },
    [],
  );
  return null;
}
