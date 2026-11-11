/**
 * The optimizer's proposal drawn on the map as an animated diff (MapLibre).
 *
 * Reveal (~1.4 s, replayable): lines that gain frequency thicken and brighten, lines that lose it
 * thin and fade, new lines draw themselves along their path, removed stops shrink away, and then
 * the choropleth of travel-time change (blue = faster, red = slower, |Δ| ≥ 30 s) fades in.
 * Line state lives in feature-state (`p` = reveal progress), so a frame costs a few dozen
 * `setFeatureState` calls and no GeoJSON re-upload. With `prefers-reduced-motion` the final
 * state is applied at once.
 */
import type { ExpressionSpecification, GeoJSONSource, Map as MlMap } from 'maplibre-gl';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useZones } from '@/api/queries';
import type { Evaluation, Route } from '@/api/types';
import { useApp, type Theme } from '@/app/store';
import { residentWeight, rgba } from '@/features/accessibility/model';
import { clockActions } from '@/features/time/clock';
import { ROUTE_LAYERS } from '@/features/network/NetworkLayers';
import { type NetworkModel } from '@/features/network/model';
import { easeOutCubic, prefersReducedMotion } from '@/lib/motion';
import { BASEMAP_PALETTES } from '@/map/basemap';
import { useMapContext } from '@/map/MapContext';
import { ensureLayer, setGeoJSON, setPaint } from '@/map/maplibreLayers';
import { deltaTimeColor, lineChange, type LineChange } from './model';
import { useOptimizer } from './store';
import { useDiff } from './useDiff';

const ZONES_SRC = 'vl-opt-zones';
const FILL = 'vl-opt-fill';
const LINES_SRC = 'vl-opt-lines';
const CASING = 'vl-opt-casing';
const LINE = 'vl-opt-line';
const STOPS_SRC = 'vl-opt-stops';
const STOPS = 'vl-opt-stops';
const NEW_PREFIX = 'vl-opt-new-';
const MAX_NEW = 4;
const FADE = { duration: 300, delay: 0 };

/** Reveal timeline (ms). */
const T = { lines: 700, stagger: 300, newFrom: 200, newDur: 1000, stops: 600, zones: 950 } as const;
export const REVEAL_TOTAL_MS = T.zones + FADE.duration;

const KIND_RANK: Record<LineChange, number> = { down: 0, same: 1, up: 2, new: 3 };

const pe: ExpressionSpecification = ['coalesce', ['feature-state', 'p'], 1];
const scaleNow: ExpressionSpecification = ['+', 1, ['*', ['-', ['get', 'scale'], 1], pe]];

const zoomWidth = (f: (k: number) => ExpressionSpecification): ExpressionSpecification => [
  'interpolate',
  ['exponential', 1.5],
  ['zoom'],
  10,
  f(0.8),
  12,
  f(1.6),
  14,
  f(2.6),
  16,
  f(4.5),
  18,
  f(8),
];

const lineWidth = zoomWidth((k) => ['*', k, scaleNow]);
const casingWidth = zoomWidth((k) => ['+', ['*', k, scaleNow], 1.6]);
const plainWidth = (scale: number): ExpressionSpecification =>
  zoomWidth((k) => ['*', k, scale] as unknown as ExpressionSpecification);

function lineOpacity(focus: string | null): ExpressionSpecification {
  const final: ExpressionSpecification = [
    'match',
    ['get', 'kind'],
    'up',
    1,
    'down',
    0.42,
    'same',
    0.55,
    1,
  ];
  const mix: ExpressionSpecification = ['+', 0.7, ['*', ['-', final, 0.7], pe]];
  return focus ? ['case', ['==', ['get', 'route_id'], focus], 1, ['*', 0.18, mix]] : mix;
}

interface LineData {
  fc: GeoJSON.FeatureCollection;
  ids: number[];
  news: { id: string; color: string; path: [number, number][] }[];
}

function buildLines(model: NetworkModel, ev: Evaluation, theme: Theme): LineData {
  const changed = new Map(ev.routes.map((r) => [r.id, r]));
  const features: GeoJSON.Feature[] = [];
  const ids: number[] = [];
  const news: LineData['news'] = [];
  for (const r of model.routes as Route[]) {
    if (r.added) {
      const path = r.patterns[0]?.path;
      if (path && news.length < MAX_NEW)
        news.push({ id: r.id, color: model.mapColor(r.id, theme), path });
      continue;
    }
    const c = changed.get(r.id);
    const { kind, scale } = c
      ? lineChange(c.trips[0], c.trips[1])
      : { kind: 'same' as LineChange, scale: 1 };
    for (const p of r.patterns) {
      const id = features.length;
      ids.push(id);
      features.push({
        type: 'Feature',
        id,
        properties: {
          route_id: r.id,
          color: model.mapColor(r.id, theme),
          kind,
          scale,
          sort: KIND_RANK[kind],
        },
        geometry: { type: 'LineString', coordinates: p.path },
      });
    }
  }
  return { fc: { type: 'FeatureCollection', features }, ids, news };
}

function removedStops(model: NetworkModel): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: model.network.stops
      .filter((s) => s.removed)
      .map((s) => ({
        type: 'Feature' as const,
        properties: { stop_id: s.id, name: s.name },
        geometry: { type: 'Point' as const, coordinates: [s.lon, s.lat] },
      })),
  };
}

function gradient(color: string, p: number): ExpressionSpecification {
  if (p >= 1) return ['step', ['line-progress'], color, 1.01, color];
  return ['step', ['line-progress'], color, Math.max(p, 0.0005), 'rgba(0,0,0,0)'];
}

function addLayers(map: MlMap, theme: Theme, anchor: string | undefined) {
  const bg = BASEMAP_PALETTES[theme].background;
  const accent = theme === 'dark' ? '#e02a40' : '#d0142c';
  const below = map.getLayer(ROUTE_LAYERS.casing) ? ROUTE_LAYERS.casing : anchor;
  ensureLayer(
    map,
    {
      id: FILL,
      type: 'fill',
      source: ZONES_SRC,
      layout: { visibility: 'none' },
      paint: {
        'fill-color': ['to-color', ['coalesce', ['feature-state', 'c'], 'rgba(0,0,0,0)']],
        'fill-opacity': 0,
        'fill-opacity-transition': FADE,
        'fill-antialias': false,
      },
    },
    below,
  );
  ensureLayer(
    map,
    {
      id: CASING,
      type: 'line',
      source: LINES_SRC,
      layout: {
        'line-cap': 'round',
        'line-join': 'round',
        'line-sort-key': ['get', 'sort'],
        visibility: 'none',
      },
      paint: { 'line-color': bg, 'line-width': casingWidth, 'line-opacity': 0.6 },
    },
    anchor,
  );
  ensureLayer(
    map,
    {
      id: LINE,
      type: 'line',
      source: LINES_SRC,
      layout: {
        'line-cap': 'round',
        'line-join': 'round',
        'line-sort-key': ['get', 'sort'],
        visibility: 'none',
      },
      paint: {
        'line-color': ['get', 'color'],
        'line-width': lineWidth,
        'line-opacity': lineOpacity(null),
      },
    },
    anchor,
  );
  ensureLayer(
    map,
    {
      id: STOPS,
      type: 'circle',
      source: STOPS_SRC,
      layout: { visibility: 'none' },
      paint: {
        'circle-radius': stopRadius(1),
        'circle-color': bg,
        'circle-stroke-color': accent,
        'circle-stroke-width': 2,
        'circle-opacity': 1,
        'circle-stroke-opacity': 1,
      },
    },
    anchor,
  );
}

const stopRadius = (k: number): ExpressionSpecification => [
  'interpolate',
  ['linear'],
  ['zoom'],
  11,
  3 * k,
  14,
  5 * k,
  17,
  7.5 * k,
];

/** Keep fills under the network and everything else on top of it, whatever mounted first. */
function order(map: MlMap, anchor: string | undefined, newIds: string[]) {
  if (map.getLayer(ROUTE_LAYERS.casing) && map.getLayer(FILL))
    map.moveLayer(FILL, ROUTE_LAYERS.casing);
  const top = anchor && map.getLayer(anchor) ? anchor : undefined;
  for (const id of [CASING, LINE, ...newIds, STOPS]) if (map.getLayer(id)) map.moveLayer(id, top);
}

function removeNew(map: MlMap, keep: Set<string>) {
  const style = map.getStyle();
  for (const l of style?.layers ?? [])
    if (l.id.startsWith(NEW_PREFIX) && !keep.has(l.id)) {
      map.removeLayer(l.id);
      if (map.getSource(l.id)) map.removeSource(l.id);
    }
}

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

export function OptimizerLayers() {
  const { map, styleVersion, anchor } = useMapContext();
  const view = useApp((s) => s.view);
  const theme = useApp((s) => s.theme);
  const revealKey = useOptimizer((s) => s.revealKey);
  const focusRoute = useOptimizer((s) => s.focusRoute);
  const active = view === 'optimizer';
  const diff = useDiff(active);
  const { data: zones } = useZones(active);
  const ev = diff?.evaluation ?? null;
  const proposal = diff?.proposal ?? null;
  const show = active && !!diff && !!proposal && !!ev && diff.scenario.length > 0;
  const [built, setBuilt] = useState(0);
  const lines = useRef<LineData | null>(null);

  // the analysis window follows the clock: stop the animation in this view
  useEffect(() => {
    if (active) clockActions.pause();
  }, [active]);

  // the base network steps back while the diff is shown
  useEffect(() => {
    useApp.setState({ diffActive: show });
    return () => useApp.setState({ diffActive: false });
  }, [show]);

  const data = useMemo(
    () => (proposal && ev ? buildLines(proposal, ev, theme) : null),
    [proposal, ev, theme],
  );

  // sources + layers + data (idempotent, re-run after every style load)
  useEffect(() => {
    if (!map || !styleVersion) return;
    setGeoJSON(map, ZONES_SRC, zones ?? { type: 'FeatureCollection', features: [] });
    setGeoJSON(map, LINES_SRC, data?.fc ?? { type: 'FeatureCollection', features: [] });
    setGeoJSON(
      map,
      STOPS_SRC,
      proposal ? removedStops(proposal) : { type: 'FeatureCollection', features: [] },
    );
    addLayers(map, theme, anchor);
    lines.current = data;
    const keep = new Set<string>();
    (data?.news ?? []).forEach((n, i) => {
      const id = `${NEW_PREFIX}${i}`;
      keep.add(id);
      const src = map.getSource(id) as GeoJSONSource | undefined;
      const fc: GeoJSON.Feature = {
        type: 'Feature',
        properties: {},
        geometry: { type: 'LineString', coordinates: n.path },
      };
      if (src) src.setData(fc);
      else map.addSource(id, { type: 'geojson', data: fc, lineMetrics: true });
      ensureLayer(
        map,
        {
          id,
          type: 'line',
          source: id,
          layout: { 'line-cap': 'round', 'line-join': 'round', visibility: 'none' },
          paint: { 'line-width': plainWidth(1.5), 'line-gradient': gradient(n.color, 0) },
        },
        anchor,
      );
      setPaint(map, id, 'line-gradient', gradient(n.color, 0));
    });
    removeNew(map, keep);
    order(map, anchor, [...keep]);
    setBuilt((b) => b + 1);
  }, [map, styleVersion, zones, data, proposal, theme, anchor]);

  // focus from the explanation list
  useEffect(() => {
    if (!map || !styleVersion) return;
    setPaint(map, LINE, 'line-opacity', lineOpacity(focusRoute));
  }, [map, styleVersion, focusRoute, built]);

  // visibility + the reveal
  useEffect(() => {
    if (!map || !styleVersion) return;
    const newIds = (lines.current?.news ?? []).map((_, i) => `${NEW_PREFIX}${i}`);
    const all = [CASING, LINE, STOPS, FILL, ...newIds];
    const vis = show ? 'visible' : 'none';
    for (const id of all) if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis);
    if (!show || !data || !ev) {
      setPaint(map, FILL, 'fill-opacity', 0);
      return;
    }

    const cur = lines.current;
    const ids = cur?.ids ?? [];
    const news = cur?.news ?? [];

    // zone colours (written once, shown at the end of the reveal)
    if (map.getSource(ZONES_SRC)) {
      map.removeFeatureState({ source: ZONES_SRC });
      const idArr = ev.zones.id;
      const dt = ev.zones.delta_time;
      for (let i = 0; i < idArr.length; i++) {
        const zid = idArr[i]!;
        const pop = zones?.features[zid]?.properties.population ?? 0;
        const color = deltaTimeColor(dt[i] ?? null, theme);
        if (!color || !(pop > 0)) continue;
        map.setFeatureState(
          { source: ZONES_SRC, id: zid },
          { c: rgba(color, residentWeight(pop) * (theme === 'dark' ? 0.72 : 0.7)) },
        );
      }
    }

    const setLines = (t: number) => {
      ids.forEach((id, i) => {
        const delay = (i / Math.max(1, ids.length)) * T.stagger;
        map.setFeatureState(
          { source: LINES_SRC, id },
          { p: easeOutCubic(clamp01((t - delay) / T.lines)) },
        );
      });
    };
    const setNew = (t: number) => {
      news.forEach((n, i) => {
        const p = easeOutCubic(clamp01((t - T.newFrom - i * 150) / T.newDur));
        setPaint(map, `${NEW_PREFIX}${i}`, 'line-gradient', gradient(n.color, p));
      });
    };
    const setStops = (t: number) => {
      const k = 1 - easeOutCubic(clamp01((t - T.newFrom) / T.stops));
      setPaint(map, STOPS, 'circle-radius', stopRadius(k));
      setPaint(map, STOPS, 'circle-opacity', k);
      setPaint(map, STOPS, 'circle-stroke-opacity', k);
    };

    if (prefersReducedMotion()) {
      setLines(1e6);
      setNew(1e6);
      setStops(1e6);
      setPaint(map, FILL, 'fill-opacity', 1);
      return;
    }

    setPaint(map, FILL, 'fill-opacity', 0);
    setLines(0);
    setNew(0);
    setStops(0);
    const t0 = performance.now();
    let raf = 0;
    let fillShown = false;
    const frame = (now: number) => {
      const t = now - t0;
      setLines(t);
      setNew(t);
      setStops(t);
      if (!fillShown && t >= T.zones) {
        fillShown = true;
        setPaint(map, FILL, 'fill-opacity', 1);
      }
      if (t < REVEAL_TOTAL_MS) raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [map, styleVersion, show, data, ev, zones, theme, revealKey, built]);

  return null;
}
