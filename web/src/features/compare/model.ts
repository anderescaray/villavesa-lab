/**
 * Pure helpers for the compare view: table rows from an evaluation, line widths and swipe maths.
 * No React, no MapLibre: unit-tested in model.test.ts.
 */
import type { Evaluation, Route } from '@/api/types';

export interface TableRow {
  id: string;
  before: number;
  after: number;
  delta: number;
  /** direction in which the change is an improvement */
  better: 'lower' | 'higher';
}

/** Accessibility index with today = 100, from the objective (population-weighted reach). */
export function accessibilityIndex(ev: Evaluation): { before: number; after: number } {
  const b = ev.baseline.objective;
  return { before: 100, after: b > 0 ? (ev.scenario.objective / b) * 100 : 100 };
}

export function summaryRows(ev: Evaluation): TableRow[] {
  const b = ev.baseline;
  const s = ev.scenario;
  const idx = accessibilityIndex(ev);
  const row = (id: string, before: number, after: number, better: TableRow['better']): TableRow => ({
    id,
    before,
    after,
    delta: after - before,
    better,
  });
  return [
    row('fleet', b.fleet, s.fleet, 'lower'),
    row('busHours', b.bus_hours, s.bus_hours, 'lower'),
    row('km', b.km, s.km, 'lower'),
    row('costDay', b.cost_eur_day, s.cost_eur_day, 'lower'),
    row('costYear', b.cost_eur_year, s.cost_eur_year, 'lower'),
    row('meanTime', b.mean_travel_time, s.mean_travel_time, 'lower'),
    row('accIndex', idx.before, idx.after, 'higher'),
    row('underserved', b.underserved_population, s.underserved_population, 'lower'),
  ];
}

/** Residents within the threshold per destination category, in display order. */
export function categoryRows(ev: Evaluation, order: readonly string[]): (TableRow & { share: [number, number] })[] {
  const ids = Object.keys(ev.baseline.categories);
  const rank = (id: string) => {
    const i = order.indexOf(id);
    return i < 0 ? 99 : i;
  };
  return ids
    .sort((a, b) => rank(a) - rank(b))
    .map((id) => {
      const b = ev.baseline.categories[id]!;
      const s = ev.scenario.categories[id] ?? b;
      return {
        id,
        before: b.pop_within,
        after: s.pop_within,
        delta: s.pop_within - b.pop_within,
        better: 'higher' as const,
        share: [b.share_within, s.share_within] as [number, number],
      };
    });
}

export type RouteChange = Evaluation['routes'][number];

/** Changed routes, largest change in daily trips first. */
export function rankRoutes(routes: readonly RouteChange[]): RouteChange[] {
  return [...routes].sort(
    (a, b) => Math.abs(b.trips[1] - b.trips[0]) - Math.abs(a.trips[1] - a.trips[0]),
  );
}

/** Line width multiplier from daily trips: thin for rare lines, bold for frequent ones. */
export function tripWidth(trips: number, maxTrips: number): number {
  if (!(maxTrips > 0) || !(trips > 0)) return 0.45;
  return 0.45 + 1.55 * Math.sqrt(Math.min(1, trips / maxTrips));
}

export const maxTripsOf = (...sets: readonly (readonly Route[])[]): number =>
  Math.max(1, ...sets.flatMap((rs) => rs.map((r) => r.stats.trips)));

/** Keyboard step for the swipe divider (fraction of the width). */
export function nextSplit(current: number, key: string, shift: boolean): number | null {
  const step = shift ? 0.1 : 0.02;
  switch (key) {
    case 'ArrowLeft':
    case 'ArrowDown':
      return Math.max(0.02, current - step);
    case 'ArrowRight':
    case 'ArrowUp':
      return Math.min(0.98, current + step);
    case 'Home':
      return 0.02;
    case 'End':
      return 0.98;
    default:
      return null;
  }
}

/** Pointer x (px) → divider fraction inside the visible area [left, right]. */
export function splitFromPointer(x: number, left: number, right: number): number {
  const w = right - left;
  return w > 0 ? Math.min(0.98, Math.max(0.02, (x - left) / w)) : 0.5;
}
