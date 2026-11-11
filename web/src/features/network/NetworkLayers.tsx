/**
 * Today's network on the map (MapLibre native layers): route lines with casings, a highlight
 * pair for the hovered/selected line, and stops. Layers are a pure function of
 * (network, theme, visible routes, highlight) — effects only push the diff into MapLibre.
 */
import type { ExpressionSpecification, FilterSpecification, Map as MlMap } from 'maplibre-gl';
import { useEffect, useMemo } from 'react';
import { useApp, type Theme } from '@/app/store';
import { useClockMinute } from '@/features/time/clock';
import { BASEMAP_PALETTES } from '@/map/basemap';
import { useMapContext } from '@/map/MapContext';
import { ensureLayer, setFilter, setGeoJSON, setPaint } from '@/map/maplibreLayers';
import { routeInService, useNetworkModel, type NetworkModel } from './model';

export const ROUTE_LAYERS = {
  casing: 'vl-routes-casing',
  line: 'vl-routes-line',
  hlCasing: 'vl-routes-hl-casing',
  hl: 'vl-routes-hl',
  stops: 'vl-stops',
  stopsRoute: 'vl-stops-route',
  stopSelected: 'vl-stop-selected',
} as const;
export const ROUTES_SOURCE = 'vl-routes';
export const STOPS_SOURCE = 'vl-stops';

const width = (scale: number): ExpressionSpecification => [
  'interpolate',
  ['exponential', 1.5],
  ['zoom'],
  10,
  0.8 * scale,
  12,
  1.6 * scale,
  14,
  2.6 * scale,
  16,
  4.5 * scale,
  18,
  8 * scale,
];

function routesGeoJSON(model: NetworkModel, theme: Theme): GeoJSON.FeatureCollection {
  // more frequent lines draw on top on shared corridors
  const freq = (id: string) => model.routeById.get(id)?.stats.trips ?? 0;
  return {
    type: 'FeatureCollection',
    features: model.routes.flatMap((r) =>
      r.patterns.map((p) => ({
        type: 'Feature' as const,
        id: undefined,
        properties: {
          route_id: r.id,
          color: model.mapColor(r.id, theme),
          sort: freq(r.id),
          kind: r.kind,
        },
        geometry: { type: 'LineString' as const, coordinates: p.path },
      })),
    ),
  };
}

function stopsGeoJSON(model: NetworkModel): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: model.network.stops.map((s) => ({
      type: 'Feature' as const,
      properties: { stop_id: s.id, name: s.name, n: s.routes.length },
      geometry: { type: 'Point' as const, coordinates: [s.lon, s.lat] },
    })),
  };
}

function addLayers(map: MlMap, theme: Theme, anchor: string | undefined) {
  const bg = BASEMAP_PALETTES[theme].background;
  const stopFill = theme === 'dark' ? '#0e0f11' : '#ffffff';
  const stopStroke = theme === 'dark' ? '#c9cdd3' : '#3a4048';
  ensureLayer(
    map,
    {
      id: ROUTE_LAYERS.casing,
      type: 'line',
      source: ROUTES_SOURCE,
      layout: { 'line-cap': 'round', 'line-join': 'round', 'line-sort-key': ['get', 'sort'] },
      paint: {
        'line-color': bg,
        'line-width': width(1.9),
        'line-opacity': 0,
        'line-opacity-transition': { duration: 200, delay: 0 },
      },
    },
    anchor,
  );
  ensureLayer(
    map,
    {
      id: ROUTE_LAYERS.line,
      type: 'line',
      source: ROUTES_SOURCE,
      layout: { 'line-cap': 'round', 'line-join': 'round', 'line-sort-key': ['get', 'sort'] },
      paint: {
        'line-color': ['get', 'color'],
        'line-width': width(1),
        'line-opacity': 0,
        'line-opacity-transition': { duration: 200, delay: 0 },
      },
    },
    anchor,
  );
  ensureLayer(
    map,
    {
      id: ROUTE_LAYERS.hlCasing,
      type: 'line',
      source: ROUTES_SOURCE,
      filter: ['==', ['get', 'route_id'], '__none__'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': bg, 'line-width': width(2.8), 'line-opacity': 0.95 },
    },
    anchor,
  );
  ensureLayer(
    map,
    {
      id: ROUTE_LAYERS.hl,
      type: 'line',
      source: ROUTES_SOURCE,
      filter: ['==', ['get', 'route_id'], '__none__'],
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': ['get', 'color'], 'line-width': width(1.6) },
    },
    anchor,
  );
  ensureLayer(
    map,
    {
      id: ROUTE_LAYERS.stops,
      type: 'circle',
      source: STOPS_SOURCE,
      minzoom: 13,
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 13, 1.6, 15, 3, 17, 4.5],
        'circle-color': stopFill,
        'circle-stroke-color': stopStroke,
        'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 13, 0.8, 16, 1.4],
        'circle-opacity': ['interpolate', ['linear'], ['zoom'], 13, 0, 13.6, 1],
        'circle-stroke-opacity': ['interpolate', ['linear'], ['zoom'], 13, 0, 13.6, 1],
      },
    },
    anchor,
  );
  ensureLayer(
    map,
    {
      id: ROUTE_LAYERS.stopsRoute,
      type: 'circle',
      source: STOPS_SOURCE,
      filter: ['in', ['get', 'stop_id'], ['literal', []]],
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, 2.2, 14, 3.6, 17, 6],
        'circle-color': stopFill,
        'circle-stroke-color': '#000000',
        'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 11, 1.2, 16, 2],
      },
    },
    anchor,
  );
  ensureLayer(
    map,
    {
      id: ROUTE_LAYERS.stopSelected,
      type: 'circle',
      source: STOPS_SOURCE,
      filter: ['==', ['get', 'stop_id'], '__none__'],
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, 5, 16, 8],
        'circle-color': stopFill,
        'circle-stroke-color': theme === 'dark' ? '#eceef1' : '#0f1216',
        'circle-stroke-width': 2.5,
      },
    },
    anchor,
  );
}

export function NetworkLayers() {
  const { map, styleVersion, anchor } = useMapContext();
  const { model } = useNetworkModel();
  const theme = useApp((s) => s.theme);
  const kinds = useApp((s) => s.kinds);
  const selected = useApp((s) => s.selectedRouteId);
  const hovered = useApp((s) => s.hoveredRouteId);
  const direction = useApp((s) => s.selectedDirection);
  const selectedStop = useApp((s) => s.selectedStopId);
  // analysis views keep the network as quiet context: thin, low-contrast, no stops
  const quiet = useApp((s) => s.view === 'accessibility');
  const minute = useClockMinute();

  // 1) sources + layers (re-added after every style load)
  useEffect(() => {
    if (!map || !model || !styleVersion) return;
    setGeoJSON(map, ROUTES_SOURCE, routesGeoJSON(model, theme));
    setGeoJSON(map, STOPS_SOURCE, stopsGeoJSON(model));
    addLayers(map, theme, anchor);
  }, [map, model, styleVersion, theme, anchor]);

  // 2) which routes are drawn: kind filter ∧ in service now (resolution: 1 simulated minute)
  const visibleKey = useMemo(() => {
    if (!model) return '';
    const t = minute * 60;
    return model.routes
      .filter((r) => kinds[r.kind] && routeInService(r, t))
      .map((r) => r.id)
      .join(',');
  }, [model, kinds, minute]);

  const highlight = quiet ? null : (hovered ?? selected);

  useEffect(() => {
    if (!map || !model || !styleVersion) return;
    const visible = visibleKey ? visibleKey.split(',') : [];
    const isVisible: ExpressionSpecification = ['in', ['get', 'route_id'], ['literal', visible]];
    const dim = theme === 'dark' ? 0.22 : 0.16;
    const lineOpacity: ExpressionSpecification = highlight
      ? ['case', isVisible, dim, ['==', ['get', 'route_id'], highlight], dim, 0]
      : ['case', isVisible, quiet ? (theme === 'dark' ? 0.5 : 0.55) : 0.92, 0];
    setPaint(map, ROUTE_LAYERS.line, 'line-opacity', lineOpacity);
    setPaint(map, ROUTE_LAYERS.line, 'line-width', width(quiet ? 0.55 : 1));
    setPaint(
      map,
      ROUTE_LAYERS.casing,
      'line-opacity',
      highlight || quiet ? 0 : ['case', isVisible, 0.85, 0],
    );
    const hlFilter: FilterSpecification = ['==', ['get', 'route_id'], highlight ?? '__none__'];
    setFilter(map, ROUTE_LAYERS.hlCasing, hlFilter);
    setFilter(map, ROUTE_LAYERS.hl, hlFilter);
  }, [map, model, styleVersion, visibleKey, highlight, theme, quiet]);

  // 3) stops of the selected line (and direction) + selected stop ring
  useEffect(() => {
    if (!map || !model || !styleVersion) return;
    const route = selected && !quiet ? model.routeById.get(selected) : undefined;
    const pattern = route?.patterns.find((p) => p.direction === direction) ?? route?.patterns[0];
    const ids = pattern?.stop_ids ?? [];
    setFilter(map, ROUTE_LAYERS.stopsRoute, ['in', ['get', 'stop_id'], ['literal', ids]]);
    setPaint(
      map,
      ROUTE_LAYERS.stopsRoute,
      'circle-stroke-color',
      route ? model.mapColor(route.id, theme) : '#000000',
    );
    setPaint(
      map,
      ROUTE_LAYERS.stops,
      'circle-opacity',
      route || quiet ? 0 : ['interpolate', ['linear'], ['zoom'], 13, 0, 13.6, 1],
    );
    setPaint(
      map,
      ROUTE_LAYERS.stops,
      'circle-stroke-opacity',
      quiet ? 0 : route ? 0.35 : ['interpolate', ['linear'], ['zoom'], 13, 0, 13.6, 1],
    );
    setFilter(map, ROUTE_LAYERS.stopSelected, [
      '==',
      ['get', 'stop_id'],
      (!quiet && selectedStop) || '__none__',
    ]);
  }, [map, model, styleVersion, selected, direction, selectedStop, theme, quiet]);

  return null;
}
