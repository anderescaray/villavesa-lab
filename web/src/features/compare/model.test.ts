import { describe, expect, it } from 'vitest';
import type { Evaluation } from '@/api/types';
import {
  accessibilityIndex,
  categoryRows,
  nextSplit,
  rankRoutes,
  splitFromPointer,
  summaryRows,
  tripWidth,
} from './model';

const kpis = (o: Partial<Evaluation['baseline']>): Evaluation['baseline'] => ({
  fleet: 10,
  bus_hours: 100,
  km: 1000,
  cost_eur_day: 5000,
  cost_eur_year: 1_800_000,
  mean_travel_time: 900,
  objective: 0.05,
  underserved_population: 1000,
  jobs_30_mean: 0.1,
  categories: { hospital: { pop_within: 100, share_within: 0.1, mean_time: 600 } },
  ...o,
});
const ev = {
  baseline: kpis({}),
  scenario: kpis({
    fleet: 12,
    objective: 0.0525,
    mean_travel_time: 870,
    categories: { hospital: { pop_within: 140, share_within: 0.14, mean_time: 580 } },
  }),
  routes: [
    { id: 'a', fleet: [1, 1], bus_hours: [1, 1], trips: [60, 62], headway_peak: [600, 580] },
    { id: 'b', fleet: [1, 2], bus_hours: [1, 2], trips: [60, 120], headway_peak: [600, 300] },
  ],
} as unknown as Evaluation;

describe('compare model', () => {
  it('indexes accessibility with today = 100', () => {
    expect(accessibilityIndex(ev)).toEqual({ before: 100, after: 105 });
  });
  it('builds the summary rows with deltas and direction', () => {
    const rows = summaryRows(ev);
    expect(rows.find((r) => r.id === 'fleet')).toMatchObject({ before: 10, after: 12, delta: 2, better: 'lower' });
    expect(rows.find((r) => r.id === 'meanTime')?.delta).toBe(-30);
    expect(rows.find((r) => r.id === 'accIndex')?.better).toBe('higher');
  });
  it('lists categories in display order with share pair', () => {
    const rows = categoryRows(ev, ['hospital']);
    expect(rows[0]).toMatchObject({ id: 'hospital', delta: 40, share: [0.1, 0.14] });
  });
  it('ranks routes by the size of the change in trips', () => {
    expect(rankRoutes(ev.routes).map((r) => r.id)).toEqual(['b', 'a']);
  });
  it('maps trips to a bounded line width', () => {
    expect(tripWidth(0, 100)).toBe(0.45);
    expect(tripWidth(100, 100)).toBeCloseTo(2);
    expect(tripWidth(25, 100)).toBeCloseTo(1.225);
    expect(tripWidth(500, 100)).toBeCloseTo(2);
  });
  it('moves the divider with the keyboard within bounds', () => {
    expect(nextSplit(0.5, 'ArrowRight', false)).toBeCloseTo(0.52);
    expect(nextSplit(0.5, 'ArrowLeft', true)).toBeCloseTo(0.4);
    expect(nextSplit(0.97, 'ArrowRight', true)).toBe(0.98);
    expect(nextSplit(0.5, 'Home', false)).toBe(0.02);
    expect(nextSplit(0.5, 'a', false)).toBeNull();
  });
  it('converts pointer x into a fraction of the visible area', () => {
    expect(splitFromPointer(416 + 500, 416, 1416)).toBeCloseTo(0.5);
    expect(splitFromPointer(0, 416, 1416)).toBe(0.02);
    expect(splitFromPointer(2000, 416, 1416)).toBe(0.98);
  });
});
