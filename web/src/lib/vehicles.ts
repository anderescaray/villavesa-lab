/**
 * Timetable-driven vehicle positions. `buildVehicleIndex` turns the `/api/vehicles` payload into
 * flat typed arrays once; `computeFrame` then runs every animation frame without allocating:
 * a binary search finds the trips that have started, a bounded backwards scan keeps those still
 * running, and each active trip is interpolated (time → distance along shape → lon/lat + bearing).
 */
import type { Vehicles } from '@/api/types';

export interface ShapeIndex {
  /** interleaved lon, lat */
  coords: Float64Array;
  cum: Float64Array;
}

export interface VehicleIndex {
  n: number;
  /** trip start/end times, trips sorted by start */
  start: Float64Array;
  end: Float64Array;
  /** waypoint offsets per trip into `t`/`d` (length n + 1) */
  offset: Uint32Array;
  t: Float64Array;
  d: Float64Array;
  shapeOf: Int32Array;
  routeOf: Uint16Array;
  routeIds: string[];
  /** headsign per trip (sorted order), straight from the API */
  headsigns: string[];
  shapes: ShapeIndex[];
  maxDuration: number;
  /** [first departure, last arrival] */
  domain: [number, number];
}

export interface Frame {
  count: number;
  /** interleaved lon, lat for active vehicles */
  positions: Float32Array;
  /** bearing in degrees clockwise from north */
  bearings: Float32Array;
  trip: Int32Array;
  route: Uint16Array;
}

export function buildVehicleIndex(v: Vehicles): VehicleIndex {
  const order = v.trips.map((_, i) => i);
  order.sort((a, b) => (v.trips[a]!.t[0] ?? 0) - (v.trips[b]!.t[0] ?? 0));
  const n = order.length;
  const routeIds: string[] = [];
  const routeIdx = new Map<string, number>();
  let total = 0;
  for (const tr of v.trips) total += tr.t.length;

  const start = new Float64Array(n);
  const end = new Float64Array(n);
  const offset = new Uint32Array(n + 1);
  const t = new Float64Array(total);
  const d = new Float64Array(total);
  const shapeOf = new Int32Array(n);
  const routeOf = new Uint16Array(n);
  const headsigns: string[] = new Array<string>(n);
  const shapeById = new Map(v.shapes.map((s, i) => [s.id, i]));
  let cursor = 0;
  let maxDuration = 0;
  let lo = Infinity;
  let hi = -Infinity;

  order.forEach((src, i) => {
    const tr = v.trips[src]!;
    offset[i] = cursor;
    const len = Math.min(tr.t.length, tr.d.length);
    let prevT = -Infinity;
    let prevD = -Infinity;
    for (let k = 0; k < len; k++) {
      // enforce non-decreasing time and distance (defensive against noisy input)
      prevT = Math.max(prevT, tr.t[k]!);
      prevD = Math.max(prevD, tr.d[k]!);
      t[cursor + k] = prevT;
      d[cursor + k] = prevD;
    }
    cursor += len;
    start[i] = len ? t[offset[i]!]! : 0;
    end[i] = len ? t[cursor - 1]! : 0;
    maxDuration = Math.max(maxDuration, end[i]! - start[i]!);
    lo = Math.min(lo, start[i]!);
    hi = Math.max(hi, end[i]!);
    shapeOf[i] = shapeById.get(tr.shape) ?? -1;
    headsigns[i] = tr.headsign;
    let r = routeIdx.get(tr.route);
    if (r === undefined) {
      r = routeIds.length;
      routeIds.push(tr.route);
      routeIdx.set(tr.route, r);
    }
    routeOf[i] = r;
  });
  offset[n] = cursor;

  const shapes = v.shapes.map((s) => {
    const coords = new Float64Array(s.path.length * 2);
    s.path.forEach(([lon, lat], k) => {
      coords[2 * k] = lon;
      coords[2 * k + 1] = lat;
    });
    return { coords, cum: Float64Array.from(s.cum_m) };
  });

  return {
    n,
    start,
    end,
    offset,
    t: t.subarray(0, cursor),
    d: d.subarray(0, cursor),
    shapeOf,
    routeOf,
    routeIds,
    headsigns,
    shapes,
    maxDuration,
    domain: n ? [lo, hi] : [0, 0],
  };
}

export function createFrame(capacity: number): Frame {
  return {
    count: 0,
    positions: new Float32Array(capacity * 2),
    bearings: new Float32Array(capacity),
    trip: new Int32Array(capacity),
    route: new Uint16Array(capacity),
  };
}

/** Largest index i in [lo, hi) with arr[i] <= x, or lo - 1 if none. */
export function lastLE(arr: ArrayLike<number>, x: number, lo = 0, hi = arr.length): number {
  let a = lo;
  let b = hi;
  while (a < b) {
    const m = (a + b) >>> 1;
    if (arr[m]! <= x) a = m + 1;
    else b = m;
  }
  return a - 1;
}

/** Distance along the trip's shape at time `time` (clamped to the trip). */
export function distanceAt(index: VehicleIndex, trip: number, time: number): number {
  const lo = index.offset[trip]!;
  const hi = index.offset[trip + 1]!;
  if (hi - lo === 0) return 0;
  const k = lastLE(index.t, time, lo, hi);
  if (k < lo) return index.d[lo]!;
  if (k >= hi - 1) return index.d[hi - 1]!;
  const t0 = index.t[k]!;
  const t1 = index.t[k + 1]!;
  const d0 = index.d[k]!;
  const d1 = index.d[k + 1]!;
  if (t1 <= t0) return d1;
  return d0 + ((time - t0) / (t1 - t0)) * (d1 - d0);
}

const DEG = 180 / Math.PI;

/** Position and bearing at distance `dist` along a shape. Writes into `out` ([lon, lat, bearing]). */
export function pointAlong(shape: ShapeIndex, dist: number, out: Float64Array | number[]): void {
  const { coords, cum } = shape;
  const n = cum.length;
  if (n === 0) {
    out[0] = 0;
    out[1] = 0;
    out[2] = 0;
    return;
  }
  if (n === 1) {
    out[0] = coords[0]!;
    out[1] = coords[1]!;
    out[2] = 0;
    return;
  }
  let k = lastLE(cum, dist);
  if (k < 0) k = 0;
  if (k > n - 2) k = n - 2;
  // skip zero-length segments for a stable bearing
  let k1 = k + 1;
  while (k1 < n - 1 && cum[k1]! <= cum[k]!) k1++;
  const c0 = cum[k]!;
  const c1 = cum[k1]!;
  const f = c1 > c0 ? Math.min(1, Math.max(0, (dist - c0) / (c1 - c0))) : 0;
  const x0 = coords[2 * k]!;
  const y0 = coords[2 * k + 1]!;
  const x1 = coords[2 * k1]!;
  const y1 = coords[2 * k1 + 1]!;
  out[0] = x0 + (x1 - x0) * f;
  out[1] = y0 + (y1 - y0) * f;
  const dx = (x1 - x0) * Math.cos(y0 / DEG);
  const dy = y1 - y0;
  out[2] = dx === 0 && dy === 0 ? 0 : (Math.atan2(dx, dy) * DEG + 360) % 360;
}

const scratch = new Float64Array(3);

/** Fill `frame` with every vehicle in service at `time`. Returns the active count. */
export function computeFrame(index: VehicleIndex, time: number, frame: Frame): number {
  const last = lastLE(index.start, time);
  let count = 0;
  const cap = frame.bearings.length;
  for (let i = last; i >= 0; i--) {
    if (index.start[i]! < time - index.maxDuration) break;
    if (index.end[i]! < time) continue;
    const s = index.shapeOf[i]!;
    const shape = index.shapes[s];
    if (!shape || count >= cap) continue;
    pointAlong(shape, distanceAt(index, i, time), scratch);
    frame.positions[2 * count] = scratch[0]!;
    frame.positions[2 * count + 1] = scratch[1]!;
    frame.bearings[count] = scratch[2]!;
    frame.trip[count] = i;
    frame.route[count] = index.routeOf[i]!;
    count++;
  }
  frame.count = count;
  return count;
}

/** Number of vehicles in service at `time` (no interpolation). */
export function activeCount(index: VehicleIndex, time: number): number {
  const last = lastLE(index.start, time);
  let c = 0;
  for (let i = last; i >= 0; i--) {
    if (index.start[i]! < time - index.maxDuration) break;
    if (index.end[i]! >= time) c++;
  }
  return c;
}

/** Vehicles in service sampled every `step` seconds over [from, to). */
export function inServiceSeries(index: VehicleIndex, from: number, to: number, step = 300) {
  const out: number[] = [];
  for (let t = from; t < to; t += step) out.push(activeCount(index, t + step / 2));
  return out;
}

/** Trip departures per route, bucketed by hour of the service day (index 0 = 00:00–01:00). */
export function departuresByHour(index: VehicleIndex, hours = 30): Map<string, number[]> {
  const out = new Map<string, number[]>();
  for (let i = 0; i < index.n; i++) {
    const r = index.routeIds[index.routeOf[i]!]!;
    let arr = out.get(r);
    if (!arr) out.set(r, (arr = new Array<number>(hours).fill(0)));
    const h = Math.floor(index.start[i]! / 3600);
    if (h >= 0 && h < hours) arr[h]! += 1;
  }
  return out;
}

/**
 * Representative headway (s) of a route around `time`: the window's length divided by the
 * departures of the busier direction, approximated as half of all departures for two-way routes.
 * Returns null when the route has < 2 departures in the window.
 */
export function headwayAround(
  perHour: number[] | undefined,
  time: number,
  directions = 2,
): number | null {
  if (!perHour) return null;
  const h = Math.floor(time / 3600);
  const deps = (perHour[h] ?? 0) * 0.5 + ((perHour[h - 1] ?? 0) + (perHour[h + 1] ?? 0)) * 0.25;
  const perDir = deps / Math.max(1, directions);
  if (perDir < 1) return null;
  return 3600 / perDir;
}
