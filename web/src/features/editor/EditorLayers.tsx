/**
 * Scenario-editor map layers (MapLibre, all null-rendering):
 *
 * 1. Delta choropleth of the 200 m cells by Δ mean travel time (diverging, blue = faster),
 *    only where |Δ| ≥ 30 s; colours in feature-state, dimmed while the next result computes.
 * 2. Emphasis of the scenario network over the quiet base network: modified / added lines (added
 *    ones get a dashed centre line), the line under edit and the hovered one; removed lines are
 *    ghosted from the baseline geometry.
 * 3. Stops with state: removed (ghost), added (solid), moved (ring + tether to the old spot).
 * 4. Tool overlay: priority corridor, new-line draft (snapped path, waypoints, proposed stops),
 *    the drag ghost of a moved stop and the add-stop insertion preview.
 *
 * Network sources are scenario-aware already (useNetworkModel follows the scenario store).
 */
import type { ExpressionSpecification, Map as MlMap } from 'maplibre-gl';
import { useEffect, useMemo } from 'react';
import { useZones } from '@/api/queries';
import type { Evaluation, LonLat } from '@/api/types';
import { useApp, type Theme } from '@/app/store';
import { useNetworkModel, type NetworkModel } from '@/features/network/model';
import { ROUTE_LAYERS, ROUTES_SOURCE } from '@/features/network/NetworkLayers';
import { useScenario } from '@/features/scenario/store';
import { BASEMAP_PALETTES } from '@/map/basemap';
import { useMapContext } from '@/map/MapContext';
import { ensureLayer, setFilter, setGeoJSON, setPaint } from '@/map/maplibreLayers';
import { DIVERGING } from '@/lib/palettes';
import { corridorOf, useBaselineModel } from './model';
import { useDraftGeometry } from './useDraft';
import { useEditor } from './state';
import { useLiveEvaluation } from './useLiveEvaluation';

export const EDITOR_LAYERS = {
  delta: 'vl-ed-delta',
  ghost: 'vl-ed-ghost',
  emCasing: 'vl-ed-em-casing',
  em: 'vl-ed-em',
  emDash: 'vl-ed-em-dash',
  tether: 'vl-ed-tether',
  stops: 'vl-ed-stops',
  overlayLine: 'vl-ed-ov-line',
  overlayCasing: 'vl-ed-ov-casing',
  overlayDash: 'vl-ed-ov-dash',
  overlayPts: 'vl-ed-ov-pts',
} as const;
const SRC = {
  delta: 'vl-ed-delta',
  ghost: 'vl-ed-ghost',
  stops: 'vl-ed-stops',
  overlay: 'vl-ed-overlay',
};

/** |Δ| bin edges (s) of the delta choropleth; below the first edge a cell is left blank. */
export const DELTA_EDGES = [30, 60, 120] as const;

export function deltaColor(d: number | null | undefined, theme: Theme): string | null {
  if (d === null || d === undefined || !Number.isFinite(d) || Math.abs(d) < DELTA_EDGES[0])
    return null;
  const pal = DIVERGING[theme];
  const step = Math.abs(d) >= DELTA_EDGES[2] ? 2 : Math.abs(d) >= DELTA_EDGES[1] ? 1 : 0;
  // faster (negative Δ) → blue arm, ordered light → dark; slower → red arm, ordered dark → light
  return d < 0 ? pal.pos[step]! : pal.neg[2 - step]!;
}

const empty: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };
const line = (coordinates: LonLat[], properties: Record<string, unknown>): GeoJSON.Feature => ({
  type: 'Feature',
  properties,
  geometry: { type: 'LineString', coordinates },
});
const point = (c: LonLat, properties: Record<string, unknown>): GeoJSON.Feature => ({
  type: 'Feature',
  properties,
  geometry: { type: 'Point', coordinates: c },
});

const lineWidth = (scale: number): ExpressionSpecification => [
  'interpolate',
  ['exponential', 1.5],
  ['zoom'],
  10,
  0.9 * scale,
  12,
  1.8 * scale,
  14,
  3 * scale,
  16,
  5 * scale,
  18,
  8.5 * scale,
];

function addLayers(map: MlMap, theme: Theme, anchor: string | undefined) {
  const bg = BASEMAP_PALETTES[theme].background;
  const ink = theme === 'dark' ? '#eceef1' : '#0f1216';
  const quiet = theme === 'dark' ? '#6b7079' : '#9aa0a8';
  const below = map.getLayer(ROUTE_LAYERS.casing) ? ROUTE_LAYERS.casing : anchor;
  ensureLayer(
    map,
    {
      id: EDITOR_LAYERS.delta,
      type: 'fill',
      source: SRC.delta,
      paint: {
        'fill-color': ['to-color', ['coalesce', ['feature-state', 'c'], 'rgba(0,0,0,0)']],
        'fill-opacity': 0,
        'fill-opacity-transition': { duration: 200, delay: 0 },
        'fill-antialias': false,
      },
    },
    below,
  );
  ensureLayer(
    map,
    {
      id: EDITOR_LAYERS.ghost,
      type: 'line',
      source: SRC.ghost,
      layout: { 'line-cap': 'butt', 'line-join': 'round' },
      paint: {
        'line-color': quiet,
        'line-width': lineWidth(0.8),
        'line-dasharray': [1.5, 1.5],
        'line-opacity': 0.8,
      },
    },
    anchor,
  );
  if (map.getSource(ROUTES_SOURCE)) {
    const none = ['==', ['get', 'route_id'], '__none__'] as ExpressionSpecification;
    ensureLayer(
      map,
      {
        id: EDITOR_LAYERS.emCasing,
        type: 'line',
        source: ROUTES_SOURCE,
        filter: none,
        layout: { 'line-cap': 'round', 'line-join': 'round', 'line-sort-key': ['get', 'sort'] },
        paint: { 'line-color': bg, 'line-width': lineWidth(2.6) },
      },
      anchor,
    );
    ensureLayer(
      map,
      {
        id: EDITOR_LAYERS.em,
        type: 'line',
        source: ROUTES_SOURCE,
        filter: none,
        layout: { 'line-cap': 'round', 'line-join': 'round', 'line-sort-key': ['get', 'sort'] },
        paint: { 'line-color': ['get', 'color'], 'line-width': lineWidth(1.4) },
      },
      anchor,
    );
    ensureLayer(
      map,
      {
        id: EDITOR_LAYERS.emDash,
        type: 'line',
        source: ROUTES_SOURCE,
        filter: none,
        layout: { 'line-cap': 'butt', 'line-join': 'round' },
        paint: {
          'line-color': bg,
          'line-width': lineWidth(0.45),
          'line-dasharray': [2, 2],
        },
      },
      anchor,
    );
  }
  ensureLayer(
    map,
    {
      id: EDITOR_LAYERS.tether,
      type: 'line',
      source: SRC.stops,
      filter: ['==', ['geometry-type'], 'LineString'],
      paint: { 'line-color': ink, 'line-width': 1.25, 'line-dasharray': [2, 2], 'line-opacity': 0.7 },
    },
    anchor,
  );
  ensureLayer(
    map,
    {
      id: EDITOR_LAYERS.stops,
      type: 'circle',
      source: SRC.stops,
      filter: ['==', ['geometry-type'], 'Point'],
      paint: {
        'circle-radius': [
          'interpolate',
          ['linear'],
          ['zoom'],
          11,
          ['match', ['get', 'state'], 'route', 2.4, 'base', 1.2, 3.2],
          14,
          ['match', ['get', 'state'], 'route', 4, 'base', 2.6, 4.6],
          17,
          ['match', ['get', 'state'], 'route', 6, 'base', 4.2, 7],
        ],
        'circle-color': [
          'match',
          ['get', 'state'],
          'added',
          ink,
          'removed',
          'rgba(0,0,0,0)',
          theme === 'dark' ? '#0e0f11' : '#ffffff',
        ],
        'circle-stroke-color': [
          'match',
          ['get', 'state'],
          'route',
          ['get', 'color'],
          'removed',
          quiet,
          'added',
          theme === 'dark' ? '#0e0f11' : '#ffffff',
          ink,
        ],
        'circle-stroke-width': [
          'match',
          ['get', 'state'],
          'base',
          1,
          'route',
          2,
          'moved',
          2.5,
          1.5,
        ],
        'circle-opacity': [
          'match',
          ['get', 'state'],
          'base',
          ['interpolate', ['linear'], ['zoom'], 12.5, 0, 13.4, 1],
          1,
        ],
        'circle-stroke-opacity': [
          'match',
          ['get', 'state'],
          'base',
          ['interpolate', ['linear'], ['zoom'], 12.5, 0, 13.4, 0.75],
          'removed',
          0.9,
          1,
        ],
      },
    },
    anchor,
  );
  // tool overlay (topmost)
  ensureLayer(
    map,
    {
      id: EDITOR_LAYERS.overlayCasing,
      type: 'line',
      source: SRC.overlay,
      filter: ['==', ['geometry-type'], 'LineString'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': bg,
        'line-width': ['match', ['get', 'kind'], 'corridor', 14, 'tether', 0, 8],
        'line-opacity': 0.9,
      },
    },
    anchor,
  );
  ensureLayer(
    map,
    {
      id: EDITOR_LAYERS.overlayLine,
      type: 'line',
      source: SRC.overlay,
      filter: ['==', ['geometry-type'], 'LineString'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': ['get', 'color'],
        'line-width': ['match', ['get', 'kind'], 'corridor', 9, 'tether', 1.5, 'raw', 1.5, 4.5],
        'line-opacity': ['match', ['get', 'kind'], 'raw', 0.6, 'tether', 0.8, 1],
      },
    },
    anchor,
  );
  ensureLayer(
    map,
    {
      id: EDITOR_LAYERS.overlayDash,
      type: 'line',
      source: SRC.overlay,
      filter: ['==', ['get', 'kind'], 'draft'],
      layout: { 'line-cap': 'butt', 'line-join': 'round' },
      paint: { 'line-color': bg, 'line-width': 1.5, 'line-dasharray': [2, 2.5] },
    },
    anchor,
  );
  ensureLayer(
    map,
    {
      id: EDITOR_LAYERS.overlayPts,
      type: 'circle',
      source: SRC.overlay,
      filter: ['==', ['geometry-type'], 'Point'],
      paint: {
        'circle-radius': [
          'match',
          ['get', 'kind'],
          'waypoint',
          4,
          'endpoint',
          7,
          'proposed',
          5,
          'excluded',
          4,
          'newstop',
          6,
          'ghost',
          7,
          'pending',
          7,
          5,
        ],
        'circle-color': [
          'match',
          ['get', 'kind'],
          'waypoint',
          bg,
          'excluded',
          bg,
          'endpoint',
          bg,
          ['get', 'color'],
        ],
        'circle-stroke-color': [
          'match',
          ['get', 'kind'],
          'excluded',
          quiet,
          'endpoint',
          ['get', 'color'],
          'waypoint',
          ['get', 'color'],
          bg,
        ],
        'circle-stroke-width': ['match', ['get', 'kind'], 'endpoint', 3, 'waypoint', 2, 2],
        'circle-opacity': ['match', ['get', 'kind'], 'ghost', 0.85, 1],
      },
    },
    anchor,
  );
}

function stopsGeoJSON(
  model: NetworkModel,
  base: NetworkModel | null,
  routeIds: string[],
  theme: Theme,
): GeoJSON.FeatureCollection {
  const onRoute = new Map<string, string>();
  for (const id of routeIds) {
    const r = model.routeById.get(id);
    if (!r) continue;
    const color = model.mapColor(id, theme);
    for (const p of r.patterns) for (const s of p.stop_ids) onRoute.set(s, color);
  }
  const features: GeoJSON.Feature[] = [];
  for (const s of model.network.stops) {
    const state = s.removed
      ? 'removed'
      : s.added
        ? 'added'
        : s.modified
          ? 'moved'
          : onRoute.has(s.id)
            ? 'route'
            : 'base';
    if (state === 'moved' && base) {
      const b = base.stopById.get(s.id);
      if (b && (b.lon !== s.lon || b.lat !== s.lat))
        features.push(line([[b.lon, b.lat], [s.lon, s.lat]], { stop_id: s.id }));
    }
    features.push(
      point([s.lon, s.lat], {
        stop_id: s.id,
        state,
        color: onRoute.get(s.id) ?? '#000000',
      }),
    );
  }
  return { type: 'FeatureCollection', features };
}

/** Line ids drawn emphasised and the ids of added lines. */
function emphasis(model: NetworkModel, extra: (string | null)[]) {
  const em = new Set<string>();
  const added: string[] = [];
  for (const r of model.routes) {
    if (r.modified || r.added) em.add(r.id);
    if (r.added) added.push(r.id);
  }
  for (const id of extra) if (id) em.add(id);
  return { em: [...em], added };
}

export function EditorLayers() {
  const { map, styleVersion, anchor } = useMapContext();
  const active = useApp((s) => s.view === 'scenario');
  const theme = useApp((s) => s.theme);
  const hovered = useApp((s) => s.hoveredRouteId);
  const { model } = useNetworkModel();
  const base = useBaselineModel();
  const hasEdits = useScenario((s) => s.edits.length > 0 && !s.peekBaseline);
  const { data: zones } = useZones(active && hasEdits);
  const { data: evaluation, stale } = useLiveEvaluation();
  const showDelta = useEditor((s) => s.showDelta);
  const routeId = useEditor((s) => s.routeId);
  const tool = useEditor((s) => s.tool);
  const direction = useEditor((s) => s.direction);
  const corridor = useEditor((s) => s.corridor);
  const drag = useEditor((s) => s.drag);
  const pending = useEditor((s) => s.pendingStop);
  const draftGeo = useDraftGeometry();

  // sources + layers after each style load
  useEffect(() => {
    if (!map || !styleVersion || !model) return;
    for (const id of [SRC.ghost, SRC.stops, SRC.overlay])
      if (!map.getSource(id)) setGeoJSON(map, id, empty);
    if (zones && !map.getSource(SRC.delta)) setGeoJSON(map, SRC.delta, zones);
    if (map.getSource(SRC.delta)) addLayers(map, theme, anchor);
    else {
      // the delta layer needs its source; add everything else meanwhile
      setGeoJSON(map, SRC.delta, empty);
      addLayers(map, theme, anchor);
    }
  }, [map, styleVersion, model, zones, theme, anchor]);

  // zones arrive after the first paint: swap the delta source's data in
  useEffect(() => {
    if (!map || !styleVersion || !zones) return;
    setGeoJSON(map, SRC.delta, zones);
  }, [map, styleVersion, zones]);

  // 1) delta choropleth
  useDeltaColors(map, styleVersion, zones ? evaluation : undefined, theme);
  useEffect(() => {
    if (!map || !styleVersion) return;
    const on = active && hasEdits && showDelta && !!evaluation && !!zones;
    setPaint(map, EDITOR_LAYERS.delta, 'fill-opacity', on ? (stale ? 0.4 : 0.85) : 0);
  }, [map, styleVersion, active, hasEdits, showDelta, evaluation, zones, stale]);

  // 2) emphasis + ghosts of removed lines
  const selectedRoute = tool === 'draw' ? null : routeId;
  const em = useMemo(
    () => (model ? emphasis(model, [selectedRoute, hovered]) : { em: [], added: [] }),
    [model, selectedRoute, hovered],
  );
  useEffect(() => {
    if (!map || !styleVersion || !model) return;
    const ids = active ? em.em : [];
    const f = ['in', ['get', 'route_id'], ['literal', ids]] as ExpressionSpecification;
    setFilter(map, EDITOR_LAYERS.emCasing, f);
    setFilter(map, EDITOR_LAYERS.em, f);
    setFilter(map, EDITOR_LAYERS.emDash, [
      'in',
      ['get', 'route_id'],
      ['literal', active ? em.added : []],
    ]);
    const removed = active && base ? model.network.removed_routes : [];
    setGeoJSON(map, SRC.ghost, {
      type: 'FeatureCollection',
      features: removed.flatMap(
        (id) => base?.routeById.get(id)?.patterns.map((p) => line(p.path, { route_id: id })) ?? [],
      ),
    });
  }, [map, styleVersion, model, base, em, active]);

  // 3) stops
  useEffect(() => {
    if (!map || !styleVersion || !model) return;
    setGeoJSON(
      map,
      SRC.stops,
      active ? stopsGeoJSON(model, base, selectedRoute ? [selectedRoute] : [], theme) : empty,
    );
  }, [map, styleVersion, model, base, active, selectedRoute, theme]);

  // 4) tool overlay
  useEffect(() => {
    if (!map || !styleVersion) return;
    const features: GeoJSON.Feature[] = [];
    const ink = theme === 'dark' ? '#eceef1' : '#0f1216';
    if (active && model) {
      const route = routeId ? model.routeById.get(routeId) : undefined;
      const color = route ? model.mapColor(route.id, theme) : ink;
      if (tool === 'priority' && route && corridor.start) {
        const c = corridor.end ? corridorOf(route, corridor.start, corridor.end, direction) : null;
        if (c) features.push(line(c.path, { kind: 'corridor', color }));
        for (const id of [corridor.start, corridor.end]) {
          const s = id ? model.stopById.get(id) : undefined;
          if (s) features.push(point([s.lon, s.lat], { kind: 'endpoint', color }));
        }
      }
      if (tool === 'draw' && draftGeo) features.push(...draftGeo);
      if (drag) {
        features.push(line([drag.from, drag.to], { kind: 'tether', color: ink }));
        features.push(point(drag.to, { kind: 'ghost', color: ink }));
      }
      if (pending) {
        const r = model.routeById.get(pending.routeId);
        features.push(
          point([pending.lon, pending.lat], {
            kind: 'pending',
            color: r ? model.mapColor(r.id, theme) : ink,
          }),
        );
      }
    }
    setGeoJSON(map, SRC.overlay, { type: 'FeatureCollection', features });
  }, [map, styleVersion, model, active, tool, routeId, direction, corridor, draftGeo, drag, pending, theme]);

  return null;
}

/** Write delta colours into feature-state when a new evaluation arrives. */
function useDeltaColors(
  map: MlMap | null,
  styleVersion: number,
  evaluation: Evaluation | undefined,
  theme: Theme,
) {
  useEffect(() => {
    if (!map || !styleVersion || !evaluation || !map.getSource(SRC.delta)) return;
    const { id, delta_time } = evaluation.zones;
    for (let i = 0; i < id.length; i++) {
      const c = deltaColor(delta_time[i], theme);
      map.setFeatureState({ source: SRC.delta, id: id[i]! }, { c });
    }
  }, [map, styleVersion, evaluation, theme]);
}
