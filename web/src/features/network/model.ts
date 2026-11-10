/**
 * Derived, memoised view of the server data for the network view. Pure functions keyed on the
 * query payload (WeakMap), so every component can call the hooks without recomputing.
 */
import { useMemo } from 'react';
import { useNetwork, useVehicles } from '@/api/queries';
import type { Network, Route, Stop, Vehicles } from '@/api/types';
import { useApp, type Theme } from '@/app/store';
import { BASEMAP_PALETTES } from '@/map/basemap';
import { ensureContrast } from '@/lib/color';
import {
  buildVehicleIndex,
  departuresByHour,
  inServiceSeries,
  type VehicleIndex,
} from '@/lib/vehicles';

export interface NetworkModel {
  network: Network;
  routes: Route[];
  routeById: Map<string, Route>;
  stopById: Map<string, Stop>;
  /** colour used on the map for a route, per theme (same hue as GTFS, contrast-nudged) */
  mapColor: (routeId: string, theme: Theme) => string;
}

const networkCache = new WeakMap<Network, NetworkModel>();

export function buildNetworkModel(network: Network): NetworkModel {
  const cached = networkCache.get(network);
  if (cached) return cached;
  const routeById = new Map(network.routes.map((r) => [r.id, r]));
  const stopById = new Map(network.stops.map((s) => [s.id, s]));
  const colorCache = new Map<string, string>();
  const mapColor = (routeId: string, theme: Theme) => {
    const key = `${routeId}|${theme}`;
    let c = colorCache.get(key);
    if (!c) {
      const base = routeById.get(routeId)?.color ?? '#888888';
      c = ensureContrast(base, BASEMAP_PALETTES[theme].background, theme === 'dark' ? 2.2 : 1.5);
      colorCache.set(key, c);
    }
    return c;
  };
  const model = { network, routes: network.routes, routeById, stopById, mapColor };
  networkCache.set(network, model);
  return model;
}

export interface VehicleModel {
  index: VehicleIndex;
  perHour: Map<string, number[]>;
  /** buses in service per `step` seconds starting at `from` */
  series: number[];
  from: number;
  to: number;
  step: number;
}

const vehicleCache = new WeakMap<Vehicles, VehicleModel>();
export const SERIES_STEP = 600;

export function buildVehicleModel(v: Vehicles): VehicleModel {
  const cached = vehicleCache.get(v);
  if (cached) return cached;
  const index = buildVehicleIndex(v);
  const from = Math.floor(index.domain[0] / 3600) * 3600;
  const to = Math.ceil(index.domain[1] / 3600) * 3600;
  const model = {
    index,
    perHour: departuresByHour(index),
    series: inServiceSeries(index, from, to, SERIES_STEP),
    from,
    to,
    step: SERIES_STEP,
  };
  vehicleCache.set(v, model);
  return model;
}

export function useNetworkModel() {
  const day = useApp((s) => s.day);
  const q = useNetwork(day);
  const model = useMemo(() => (q.data ? buildNetworkModel(q.data) : null), [q.data]);
  return { model, query: q };
}

export function useVehicleModel() {
  const day = useApp((s) => s.day);
  const q = useVehicles(day);
  const model = useMemo(() => (q.data ? buildVehicleModel(q.data) : null), [q.data]);
  return { model, query: q };
}

/** Whether a route has service around `time` (between first departure and last arrival). */
export function routeInService(r: Route, time: number): boolean {
  return time >= r.stats.first_dep - 300 && time <= r.stats.last_dep + r.stats.run_time;
}

/** Search across line number, name and served stop names (accent-insensitive). */
const fold = (s: string) =>
  s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase();

export function matchRoute(r: Route, query: string, stopById: Map<string, Stop>): boolean {
  const q = fold(query.trim());
  if (!q) return true;
  if (fold(r.short_name).includes(q) || fold(r.long_name).includes(q)) return true;
  if (/^\d+$/.test(q) && fold(r.short_name).replace(/^[a-z]0*/, '') === q.replace(/^0+/, '')) return true;
  for (const p of r.patterns) {
    if (fold(p.headsign).includes(q)) return true;
    for (const id of p.stop_ids) {
      const s = stopById.get(id);
      if (s && fold(s.name).includes(q)) return true;
    }
  }
  return false;
}

const headsignCache = new WeakMap<VehicleModel, Map<number, string | null>>();

/**
 * Headsign of a vehicle trip. `/api/vehicles` carries no headsign/direction (see proposed
 * contract changes), so we match the trip's shape end point to the closest pattern end.
 */
export function headsignForTrip(network: NetworkModel, vehicles: VehicleModel, trip: number): string | null {
  let cache = headsignCache.get(vehicles);
  if (!cache) headsignCache.set(vehicles, (cache = new Map()));
  const shapeIdx = vehicles.index.shapeOf[trip] ?? -1;
  const key = shapeIdx * 10000 + (vehicles.index.routeOf[trip] ?? 0);
  if (cache.has(key)) return cache.get(key) ?? null;
  const routeId = vehicles.index.routeIds[vehicles.index.routeOf[trip] ?? 0];
  const route = routeId ? network.routeById.get(routeId) : undefined;
  const shape = vehicles.index.shapes[shapeIdx];
  let best: string | null = null;
  if (route && shape && shape.coords.length >= 2) {
    const ex = shape.coords[shape.coords.length - 2]!;
    const ey = shape.coords[shape.coords.length - 1]!;
    let bestD = Infinity;
    for (const p of route.patterns) {
      const last = p.path[p.path.length - 1];
      if (!last) continue;
      const d = (last[0] - ex) ** 2 + (last[1] - ey) ** 2;
      if (d < bestD) {
        bestD = d;
        best = p.headsign;
      }
    }
  }
  cache.set(key, best);
  return best;
}
