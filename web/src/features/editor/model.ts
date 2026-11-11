/**
 * Pure helpers of the scenario editor: geometry on patterns (corridors, insertion points),
 * headway snapping, new-line naming/colours and human-readable edit summaries.
 */
import { useMemo } from 'react';
import { useNetwork } from '@/api/queries';
import type { AddRouteEdit, ScenarioEdit } from '@/api/scenario';
import type { LonLat, Pattern, Route } from '@/api/types';
import { useApp } from '@/app/store';
import { buildNetworkModel, type NetworkModel } from '@/features/network/model';
import type { TFunction } from '@/i18n';
import type { Lang } from '@/i18n';
import { displayName, formatMinutes } from '@/lib/format';

/** Today's network (never the scenario): reference values for "current → new". */
export function useBaselineModel(): NetworkModel | null {
  const day = useApp((s) => s.day);
  const q = useNetwork(day, null);
  return useMemo(() => (q.data ? buildNetworkModel(q.data) : null), [q.data]);
}

// ------------------------------------------------------------------ headway

/** Slider stops (minutes): fine where it matters (2–10), coarse above. */
export const HEADWAY_STEPS_MIN = [2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 45, 60] as const;

export const nearestStepIndex = (seconds: number) => {
  const m = seconds / 60;
  let best = 0;
  HEADWAY_STEPS_MIN.forEach((v, i) => {
    if (Math.abs(v - m) < Math.abs(HEADWAY_STEPS_MIN[best]! - m)) best = i;
  });
  return best;
};

// ------------------------------------------------------------------ geometry

const R = 6371008.8;
const rad = Math.PI / 180;

/** Local equirectangular projection around Pamplona: metres. Plenty precise at city scale. */
export function toXY(p: LonLat, lat0 = 42.81): [number, number] {
  return [p[0] * rad * R * Math.cos(lat0 * rad), p[1] * rad * R];
}

export function distanceM(a: LonLat, b: LonLat): number {
  const [ax, ay] = toXY(a);
  const [bx, by] = toXY(b);
  return Math.hypot(ax - bx, ay - by);
}

export function cumulative(path: LonLat[]): number[] {
  const out = [0];
  for (let i = 1; i < path.length; i++) out.push(out[i - 1]! + distanceM(path[i - 1]!, path[i]!));
  return out;
}

/** Closest point of a polyline to `p`: distance from the line and offset along it (m). */
export function project(path: LonLat[], p: LonLat): { offset: number; distance: number } {
  const cum = cumulative(path);
  const [px, py] = toXY(p);
  let best = { offset: 0, distance: Infinity };
  for (let i = 0; i < path.length - 1; i++) {
    const [ax, ay] = toXY(path[i]!);
    const [bx, by] = toXY(path[i + 1]!);
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = Math.max(dx * dx + dy * dy, 1e-9);
    const t = Math.min(1, Math.max(0, ((px - ax) * dx + (py - ay) * dy) / len2));
    const d = Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
    if (d < best.distance) best = { offset: cum[i]! + t * Math.sqrt(len2), distance: d };
  }
  return best;
}

/** Sub-path between two offsets (m) along `path`. */
export function slicePath(path: LonLat[], from: number, to: number): LonLat[] {
  const cum = cumulative(path);
  const at = (o: number): LonLat => {
    let i = 0;
    while (i < cum.length - 2 && cum[i + 1]! < o) i++;
    const seg = Math.max(cum[i + 1]! - cum[i]!, 1e-9);
    const t = Math.min(1, Math.max(0, (o - cum[i]!) / seg));
    const a = path[i]!;
    const b = path[i + 1] ?? a;
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  };
  const out: LonLat[] = [at(from)];
  for (let i = 0; i < path.length; i++) if (cum[i]! > from && cum[i]! < to) out.push(path[i]!);
  out.push(at(to));
  return out;
}

/**
 * The corridor between two stops of a line: the pattern where `start` precedes `end` (either
 * direction), its consecutive stop ids and the path between them.
 */
export function corridorOf(
  route: Route,
  start: string,
  end: string,
  preferDirection = 0,
): { pattern: Pattern; stopIds: string[]; path: LonLat[] } | null {
  const ordered = [...route.patterns].sort(
    (a, b) => Number(b.direction === preferDirection) - Number(a.direction === preferDirection),
  );
  for (const p of ordered) {
    const i = p.stop_ids.indexOf(start);
    const j = p.stop_ids.indexOf(end, i + 1);
    if (i >= 0 && j > i) {
      const from = p.stop_offsets[i] ?? 0;
      const to = p.stop_offsets[j] ?? from;
      return { pattern: p, stopIds: p.stop_ids.slice(i, j + 1), path: slicePath(p.path, from, to) };
    }
  }
  return null;
}

/** Insertion point of a new stop on a pattern: the preceding stop of the nearest path point. */
export function insertionOn(
  pattern: Pattern,
  p: LonLat,
): { afterStopId: string; distance: number; point: LonLat } | null {
  if (pattern.path.length < 2 || !pattern.stop_ids.length) return null;
  const { offset, distance } = project(pattern.path, p);
  let k = 0;
  for (let i = 0; i < pattern.stop_offsets.length; i++)
    if ((pattern.stop_offsets[i] ?? 0) <= offset) k = i;
  if (k >= pattern.stop_ids.length - 1) k = pattern.stop_ids.length - 2; // never after the terminus
  const point = slicePath(pattern.path, offset, offset)[0]!;
  return { afterStopId: pattern.stop_ids[Math.max(0, k)]!, distance, point };
}

// ------------------------------------------------------------------ new lines

/** Candidate colours for new lines; the UI offers those farthest from existing line colours. */
const CANDIDATES = [
  '#1F6FEB',
  '#7C3AED',
  '#0E9F6E',
  '#DB2777',
  '#0891B2',
  '#65A30D',
  '#CA8A04',
  '#334155',
  '#9A3412',
  '#A21CAF',
];

const hexRgb = (h: string) => {
  const n = parseInt(h.replace('#', '').slice(0, 6), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255] as const;
};
const colorDist = (a: string, b: string) => {
  const [r1, g1, b1] = hexRgb(a);
  const [r2, g2, b2] = hexRgb(b);
  const rm = (r1 + r2) / 2; // "redmean" approximation of perceptual distance
  return Math.sqrt(
    (2 + rm / 256) * (r1 - r2) ** 2 + 4 * (g1 - g2) ** 2 + (2 + (255 - rm) / 256) * (b1 - b2) ** 2,
  );
};

export function newLinePalette(existing: string[], n = 6): string[] {
  // greedy max-min: each pick is the candidate farthest from existing lines AND earlier picks
  const picked: string[] = [];
  const pool = [...CANDIDATES];
  while (picked.length < n && pool.length) {
    let best = 0;
    let bestD = -1;
    pool.forEach((c, i) => {
      const d = Math.min(...[...existing, ...picked].map((e) => colorDist(c, e)), 9999);
      if (d > bestD) {
        bestD = d;
        best = i;
      }
    });
    picked.push(pool.splice(best, 1)[0]!);
  }
  return picked;
}

const LETTERS = 'ABCDEFGHJKMNPQRSTUVWXYZ';

/** Next free short name ("A", "B", …) and route id ("new-A") given the current edits. */
export function nextLineName(edits: ScenarioEdit[], existingShort: string[]): string {
  const taken = new Set([
    ...existingShort,
    ...edits.filter((e): e is AddRouteEdit => e.type === 'add_route').map((e) => e.short_name),
  ]);
  for (const l of LETTERS) if (!taken.has(l)) return l;
  return `X${edits.length}`;
}

export const newRouteId = (shortName: string, edits: ScenarioEdit[]) => {
  const ids = new Set(edits.filter((e) => e.type === 'add_route').map((e) => e.route_id));
  const base = `new-${shortName.replace(/[^\w-]/g, '') || 'line'}`;
  let id = base;
  for (let i = 2; ids.has(id); i++) id = `${base}-${i}`;
  return id;
};

export const newStopId = () =>
  `new-s-${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36)}`;

// ------------------------------------------------------------------ edit summaries

export interface EditSummary {
  /** route id for the badge (null for multi-line edits) */
  routeId: string | null;
  /** badge override for routes that only exist in the edit (new lines) */
  badge?: { shortName: string; color: string };
  title: string;
  detail: string;
}

const periodKey = (p: string | undefined) =>
  p === 'peak'
    ? 'editor.period.peak'
    : p === 'offpeak'
      ? 'editor.period.offpeak'
      : 'editor.period.all';

export function summarize(
  e: ScenarioEdit,
  t: TFunction,
  lang: Lang,
  base: NetworkModel | null,
): EditSummary {
  const short = (id: string | null | undefined) =>
    (id && base?.routeById.get(id)?.short_name) || id || '';
  const stopName = (id: string) => {
    const s = base?.stopById.get(id);
    return s ? displayName(s.name) : id;
  };
  switch (e.type) {
    case 'set_headway':
      return {
        routeId: e.route_id,
        title: t('editor.sum.headway', { min: formatMinutes(e.headway, lang) }),
        detail: t(periodKey(e.period)),
      };
    case 'scale_frequency':
      return {
        routeId: e.route_id,
        title: t('editor.sum.scale', {
          pct: `${e.factor >= 1 ? '+' : '−'}${Math.round(Math.abs(e.factor - 1) * 100)}`,
        }),
        detail: t(periodKey(e.period)),
      };
    case 'speed_up':
      return {
        routeId: e.route_id,
        title: t('editor.sum.priority', {
          n: e.stop_ids.length - 1,
          pct: Math.round((e.factor - 1) * 100),
        }),
        detail: `${stopName(e.stop_ids[0] ?? '')} → ${stopName(e.stop_ids[e.stop_ids.length - 1] ?? '')}${e.route_id ? '' : ` · ${t('editor.sum.allLines')}`}`,
      };
    case 'remove_stop':
      return {
        routeId: e.route_id ?? null,
        title: t('editor.sum.removeStop'),
        detail: `${stopName(e.stop_id)}${e.route_id ? '' : ` · ${t('editor.sum.allLines')}`}`,
      };
    case 'move_stop': {
      const s = base?.stopById.get(e.stop_id);
      const d = s ? Math.round(distanceM([s.lon, s.lat], [e.lon, e.lat])) : null;
      return {
        routeId: null,
        title: t('editor.sum.moveStop', { m: d ?? '—' }),
        detail: stopName(e.stop_id),
      };
    }
    case 'add_stop':
      return {
        routeId: e.route_id,
        title: t('editor.sum.addStop', { line: short(e.route_id) }),
        detail: e.name || t('editor.stop.unnamed'),
      };
    case 'remove_route':
      return {
        routeId: e.route_id,
        title: t('editor.sum.removeRoute', { line: short(e.route_id) }),
        detail: base?.routeById.get(e.route_id)?.long_name
          ? displayName(base.routeById.get(e.route_id)!.long_name)
          : '',
      };
    case 'add_route':
      return {
        routeId: null,
        badge: { shortName: e.short_name, color: e.color },
        title: t('editor.sum.addRoute', {
          name: e.short_name,
          n: e.stops.length,
          min: formatMinutes(e.headway, lang),
        }),
        detail: e.bidirectional ? t('editor.draw.bidirectional') : t('editor.draw.oneWay'),
      };
  }
}
