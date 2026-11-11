/**
 * Pointer interaction of the scenario editor. The active tool decides what a click means; in
 * every editor tool the map never drops an isochrone (that only happens in the network view).
 *
 * - select / frequency: click a line → edit it; click a stop → stop inspector (select only)
 * - priority: click a line, then a start and an end stop on it
 * - stop: click a stop → inspector; drag a stop → move it; in "add" mode click near the line
 * - draw: click → waypoint (or a new stop in "stops" mode); double-click finishes
 */
import type { MapGeoJSONFeature, MapMouseEvent } from 'maplibre-gl';
import { useEffect } from 'react';
import type { LonLat } from '@/api/types';
import { useApp } from '@/app/store';
import { clock } from '@/features/time/clock';
import { routeInService, useNetworkModel, type NetworkModel } from '@/features/network/model';
import { ROUTE_LAYERS } from '@/features/network/NetworkLayers';
import { useScenario } from '@/features/scenario/store';
import { useMapContext } from '@/map/MapContext';
import { EDITOR_LAYERS } from './EditorLayers';
import { corridorOf, distanceM, insertionOn, newStopId } from './model';
import { useEditor } from './state';
import { finishDraft } from './actions';

/** Max distance (m) from the line for an add-stop click. */
export const ADD_STOP_MAX_M = 120;

function hit(map: maplibregl.Map, x: number, y: number, layers: string[], r: number) {
  const existing = layers.filter((l) => map.getLayer(l));
  if (!existing.length) return [] as MapGeoJSONFeature[];
  return map.queryRenderedFeatures(
    [
      [x - r, y - r],
      [x + r, y + r],
    ],
    { layers: existing },
  );
}

function stopAt(map: maplibregl.Map, x: number, y: number, routeOnly = false): string | null {
  for (const f of hit(map, x, y, [EDITOR_LAYERS.stops], 7)) {
    const state = f.properties?.state as string | undefined;
    if (state === 'removed') continue;
    if (state === 'base' && map.getZoom() < 13) continue;
    if (routeOnly && state !== 'route' && state !== 'moved' && state !== 'added') continue;
    return String(f.properties?.stop_id);
  }
  return null;
}

function lineAt(map: maplibregl.Map, model: NetworkModel, x: number, y: number): string | null {
  const { kinds } = useApp.getState();
  const time = clock.getState().time;
  for (const f of hit(map, x, y, [EDITOR_LAYERS.em, ROUTE_LAYERS.line], 4)) {
    const id = f.properties?.route_id as string | undefined;
    const r = id ? model.routeById.get(id) : undefined;
    if (r && kinds[r.kind] && routeInService(r, time)) return r.id;
  }
  return null;
}

export function EditorInteractions() {
  const { map } = useMapContext();
  const { model } = useNetworkModel();
  const active = useApp((s) => s.view === 'scenario');
  const tool = useEditor((s) => s.tool);

  useEffect(() => {
    if (!map || !model || !active) return;
    const canvas = map.getCanvas();
    let raf = 0;
    let pending: { x: number; y: number } | null = null;
    let dragging: { stopId: string; from: LonLat; moved: boolean } | null = null;

    const baseCursor = () => {
      const ed = useEditor.getState();
      return ed.tool === 'draw' || ed.addingStop ? 'crosshair' : '';
    };

    const evaluateHover = () => {
      raf = 0;
      if (!pending || dragging) return;
      const { x, y } = pending;
      const ed = useEditor.getState();
      const app = useApp.getState();
      if (ed.tool === 'draw' || ed.addingStop) {
        canvas.style.cursor = 'crosshair';
        app.hoverRoute(null);
        return;
      }
      if (ed.tool === 'stop' || ed.tool === 'select') {
        const s = stopAt(map, x, y);
        if (s) {
          canvas.style.cursor = ed.tool === 'stop' ? 'grab' : 'pointer';
          app.hoverRoute(null);
          return;
        }
      }
      if (ed.tool === 'priority' && ed.routeId) {
        canvas.style.cursor = stopAt(map, x, y, true) ? 'pointer' : '';
        return;
      }
      if (ed.tool === 'stop') {
        canvas.style.cursor = '';
        return;
      }
      const line = lineAt(map, model, x, y);
      canvas.style.cursor = line ? 'pointer' : baseCursor();
      app.hoverRoute(line);
    };

    const onMove = (e: MapMouseEvent) => {
      if (dragging) {
        const to: LonLat = [e.lngLat.lng, e.lngLat.lat];
        dragging.moved = true;
        useEditor.getState().set({ drag: { stopId: dragging.stopId, from: dragging.from, to } });
        return;
      }
      pending = e.point;
      if (!raf) raf = requestAnimationFrame(evaluateHover);
    };
    const onLeave = () => {
      pending = null;
      if (!dragging) canvas.style.cursor = baseCursor();
      useApp.getState().hoverRoute(null);
    };

    const onDown = (e: MapMouseEvent) => {
      const ed = useEditor.getState();
      if (ed.tool !== 'stop' || ed.addingStop || e.originalEvent.button !== 0) return;
      const id = stopAt(map, e.point.x, e.point.y);
      const s = id ? model.stopById.get(id) : undefined;
      if (!s || !id) return;
      e.preventDefault();
      map.dragPan.disable();
      dragging = { stopId: id, from: [s.lon, s.lat], moved: false };
      canvas.style.cursor = 'grabbing';
      ed.set({ stopId: id });
    };
    const onUp = (e: MapMouseEvent) => {
      if (!dragging) return;
      const d = dragging;
      dragging = null;
      map.dragPan.enable();
      canvas.style.cursor = 'grab';
      const ed = useEditor.getState();
      ed.set({ drag: null });
      const to: LonLat = [e.lngLat.lng, e.lngLat.lat];
      if (!d.moved || distanceM(d.from, to) < 5) return;
      const edit = {
        type: 'move_stop' as const,
        stop_id: d.stopId,
        lon: Math.round(to[0] * 1e6) / 1e6,
        lat: Math.round(to[1] * 1e6) / 1e6,
      };
      const sc = useScenario.getState();
      const idx = sc.edits.findIndex((x) => x.type === 'move_stop' && x.stop_id === d.stopId);
      if (idx >= 0) sc.update(idx, edit);
      else sc.add(edit);
    };

    const onClick = (e: MapMouseEvent) => {
      const { x, y } = e.point;
      const app = useApp.getState();
      const ed = useEditor.getState();
      const lngLat: LonLat = [e.lngLat.lng, e.lngLat.lat];
      if (app.panelOpen && window.innerWidth < 1024 && ed.tool !== 'draw') {
        app.set({ panelOpen: false });
        return;
      }
      switch (ed.tool) {
        case 'draw': {
          const draft = ed.draft;
          if (!draft) return;
          if (draft.placeStops) {
            ed.setDraft({
              newStops: [
                ...draft.newStops,
                {
                  key: newStopId(),
                  stopId: null,
                  lon: lngLat[0],
                  lat: lngLat[1],
                  name: '',
                  offset: 0,
                },
              ],
            });
            return;
          }
          const last = draft.waypoints[draft.waypoints.length - 1];
          if (last && distanceM(last, lngLat) < 8) return; // double-click second hit
          ed.setDraft({ waypoints: [...draft.waypoints, lngLat] });
          return;
        }
        case 'priority': {
          if (!ed.routeId) {
            const line = lineAt(map, model, x, y);
            if (line) ed.pickRoute(line);
            return;
          }
          const stop = stopAt(map, x, y, true);
          if (!stop) {
            const line = lineAt(map, model, x, y);
            if (line && line !== ed.routeId) ed.pickRoute(line);
            return;
          }
          const route = model.routeById.get(ed.routeId);
          const c = ed.corridor;
          if (!c.start || (c.start && c.end) || stop === c.start) {
            ed.setCorridor({ start: stop, end: null });
          } else if (route) {
            const fwd = corridorOf(route, c.start, stop, ed.direction);
            if (fwd) {
              ed.set({ direction: fwd.pattern.direction });
              ed.setCorridor({ end: stop });
            } else ed.setCorridor({ start: stop, end: null });
          }
          return;
        }
        case 'stop': {
          if (ed.addingStop && ed.routeId) {
            const route = model.routeById.get(ed.routeId);
            const pattern =
              route?.patterns.find((p) => p.direction === ed.direction) ?? route?.patterns[0];
            const ins = pattern ? insertionOn(pattern, lngLat) : null;
            if (!ins || ins.distance > ADD_STOP_MAX_M) {
              ed.set({ pendingStop: null });
              window.dispatchEvent(new CustomEvent('vlab:editor-addstop-far'));
              return;
            }
            ed.set({
              pendingStop: {
                lon: lngLat[0],
                lat: lngLat[1],
                routeId: ed.routeId,
                direction: pattern!.direction,
                afterStopId: ins.afterStopId,
                name: ed.pendingStop?.name ?? '',
              },
            });
            return;
          }
          const stop = stopAt(map, x, y);
          ed.set({ stopId: stop });
          return;
        }
        case 'select':
        case 'frequency': {
          if (ed.tool === 'select') {
            const stop = stopAt(map, x, y);
            if (stop) {
              ed.set({ tool: 'stop', stopId: stop });
              return;
            }
          }
          const line = lineAt(map, model, x, y);
          if (line) {
            app.hoverRoute(null);
            ed.pickRoute(line);
            if (ed.tool === 'select') ed.set({ tool: 'frequency' });
          }
          return;
        }
      }
    };

    const onDbl = (e: MapMouseEvent) => {
      if (useEditor.getState().tool !== 'draw') return;
      e.preventDefault();
      finishDraft();
    };

    const draw = useEditor.getState().tool === 'draw';
    if (draw) map.doubleClickZoom.disable();
    canvas.style.cursor = baseCursor();
    map.on('mousemove', onMove);
    map.on('mouseout', onLeave);
    map.on('mousedown', onDown);
    map.on('mouseup', onUp);
    map.on('click', onClick);
    map.on('dblclick', onDbl);
    return () => {
      cancelAnimationFrame(raf);
      if (dragging) map.dragPan.enable();
      map.doubleClickZoom.enable();
      canvas.style.cursor = '';
      useApp.getState().hoverRoute(null);
      map.off('mousemove', onMove);
      map.off('mouseout', onLeave);
      map.off('mousedown', onDown);
      map.off('mouseup', onUp);
      map.off('click', onClick);
      map.off('dblclick', onDbl);
    };
  }, [map, model, active, tool]);

  return null;
}
