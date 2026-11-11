/**
 * Pointer interaction on the map for the network view. Hit priority: bus → stop → line →
 * empty map (drops an isochrone). Hover highlights lines and sets the cursor. All hit tests run
 * at most once per animation frame.
 */
import type { MapGeoJSONFeature, MapMouseEvent } from 'maplibre-gl';
import { useEffect } from 'react';
import { useApp } from '@/app/store';
import { clock } from '@/features/time/clock';
import { snapIsoStart } from '@/features/isochrone/useIsochroneRequest';
import { deckRegistry } from '@/map/deckRegistry';
import { useMapContext } from '@/map/MapContext';
import { BUS_LAYER_ID, useBusHover } from './BusesLayer';
import { ROUTE_LAYERS } from './NetworkLayers';
import { routeInService, useNetworkModel, type NetworkModel } from './model';

const STOP_LAYERS = [ROUTE_LAYERS.stopsRoute, ROUTE_LAYERS.stops, ROUTE_LAYERS.stopSelected];
const LINE_LAYERS = [ROUTE_LAYERS.hl, ROUTE_LAYERS.line];

function hit(
  map: maplibregl.Map,
  x: number,
  y: number,
  layers: string[],
  r: number,
): MapGeoJSONFeature[] {
  const existing = layers.filter((l) => map.getLayer(l));
  if (!existing.length) return [];
  return map.queryRenderedFeatures(
    [
      [x - r, y - r],
      [x + r, y + r],
    ],
    { layers: existing },
  );
}

/** Stop hits only count where stops are actually drawn (zoom ≥ 13 or on the selected line). */
function stopHit(map: maplibregl.Map, x: number, y: number) {
  const zoom = map.getZoom();
  const layers = useApp.getState().selectedRouteId
    ? [ROUTE_LAYERS.stopsRoute, ROUTE_LAYERS.stopSelected]
    : zoom >= 13.4
      ? STOP_LAYERS
      : [ROUTE_LAYERS.stopSelected];
  return hit(map, x, y, layers, 6)[0];
}

function lineHit(map: maplibregl.Map, model: NetworkModel, x: number, y: number) {
  const { kinds } = useApp.getState();
  const time = clock.getState().time;
  for (const f of hit(map, x, y, LINE_LAYERS, 3)) {
    const id = f.properties?.route_id as string | undefined;
    const r = id ? model.routeById.get(id) : undefined;
    if (r && kinds[r.kind] && routeInService(r, time)) return r.id;
  }
  return null;
}

export function MapInteractions() {
  const { map } = useMapContext();
  const { model } = useNetworkModel();
  const view = useApp((s) => s.view);

  useEffect(() => {
    if (!map || !model || view !== 'network') return;
    const canvas = map.getCanvas();
    let raf = 0;
    let pending: { x: number; y: number } | null = null;

    const evaluateHover = () => {
      raf = 0;
      if (!pending) return;
      const { x, y } = pending;
      const app = useApp.getState();
      if (useBusHover.getState().hover) {
        canvas.style.cursor = 'pointer';
        app.hoverRoute(useBusHover.getState().hover?.route ?? null);
        return;
      }
      if (stopHit(map, x, y)) {
        canvas.style.cursor = 'pointer';
        app.hoverRoute(null);
        return;
      }
      const line = lineHit(map, model, x, y);
      canvas.style.cursor = line ? 'pointer' : 'crosshair';
      app.hoverRoute(line);
    };

    const onMove = (e: MapMouseEvent) => {
      pending = e.point;
      if (!raf) raf = requestAnimationFrame(evaluateHover);
    };
    const onLeave = () => {
      pending = null;
      canvas.style.cursor = '';
      useApp.getState().hoverRoute(null);
      useBusHover.setState({ hover: null });
    };
    const onClick = (e: MapMouseEvent) => {
      const { x, y } = e.point;
      const app = useApp.getState();
      if (app.panelOpen && window.innerWidth < 1024) {
        app.set({ panelOpen: false }); // overlay drawer: first tap on the map dismisses it
        return;
      }
      const bus = deckRegistry.pick(x, y, [BUS_LAYER_ID], 4);
      const busHover = useBusHover.getState().hover;
      if (bus && busHover) {
        app.selectRoute(busHover.route);
        return;
      }
      const stop = stopHit(map, x, y);
      if (stop) {
        app.selectStop(String(stop.properties?.stop_id));
        return;
      }
      const line = lineHit(map, model, x, y);
      if (line) {
        app.hoverRoute(null);
        app.selectRoute(line);
        return;
      }
      app.setIsoOrigin([e.lngLat.lng, e.lngLat.lat], snapIsoStart(clock.getState().time));
    };

    canvas.style.cursor = 'crosshair';
    map.on('mousemove', onMove);
    map.on('mouseout', onLeave);
    map.on('click', onClick);
    return () => {
      cancelAnimationFrame(raf);
      canvas.style.cursor = '';
      map.off('mousemove', onMove);
      map.off('mouseout', onLeave);
      map.off('click', onClick);
    };
  }, [map, model, view]);

  return null;
}
