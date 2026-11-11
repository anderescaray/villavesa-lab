import { describe, expect, it } from 'vitest';
import type { Accessibility } from '@/api/types';
import {
  binTotals,
  curvePoints,
  metricScale,
  readConcentration,
  residentWeight,
  shareAt,
  sortCategories,
  zoneColors,
} from './model';

const acc = (time: (number | null)[], pop: number[]): Accessibility => ({
  window: { day: 'weekday', start: 28800, duration: 3600 },
  threshold: 1800,
  population: pop.reduce((a, b) => a + b, 0),
  categories: [],
  zones: {
    id: pop.map((_, i) => i),
    population: pop,
    time: { hospital: time },
    jobs_30: pop.map(() => 0.12),
    access_index: pop.map(() => 0),
    mean_time: pop.map(() => null),
    income: pop.map(() => null),
    section_id: pop.map(() => 'x'),
  },
  equity: { quintiles: [], concentration_index: {} },
  summary: { mean_travel_time: 0, underserved_population: 0, objective: 0, jobs_30_mean: 0 },
});

describe('metric scales', () => {
  it('bins travel time in 10-minute steps with unreachable apart', () => {
    const s = metricScale('time', 'light', 1800);
    expect(s.bins).toHaveLength(8);
    expect(s.binOf(0)).toBe(0);
    expect(s.binOf(599)).toBe(0);
    expect(s.binOf(600)).toBe(1);
    expect(s.binOf(3599)).toBe(5);
    expect(s.binOf(5000)).toBe(6);
    expect(s.binOf(null)).toBe(7);
    expect(s.bins[7]!.kind).toBe('none');
  });
  it('makes short times the most prominent step on both themes', () => {
    // light: darkest first; dark: lightest first
    expect(metricScale('time', 'light', 1800).bins[0]!.color).toBe('#0d366b');
    expect(metricScale('time', 'dark', 1800).bins[0]!.color).toBe('#cde2fb');
  });
  it('splits the under-served view by minutes over the threshold', () => {
    const s = metricScale('gap', 'light', 1800);
    expect(s.binOf(1700)).toBe(0);
    expect(s.binOf(1800)).toBe(1);
    expect(s.binOf(2500)).toBe(2);
    expect(s.binOf(4000)).toBe(3);
    expect(s.binOf(null)).toBe(3);
  });
});

describe('zone colours', () => {
  it('hides empty cells and weights the rest by residents', () => {
    expect(residentWeight(0)).toBe(0);
    expect(residentWeight(1)).toBeGreaterThan(0.3);
    expect(residentWeight(400)).toBe(1);
    expect(residentWeight(4000)).toBe(1);
    const colors = zoneColors(acc([300, 300, null], [0, 400, 10]), 'time', 'hospital', 'light');
    expect(colors[0]).toBe('rgba(0,0,0,0)');
    expect(colors[1]).toMatch(/^rgba\(13,54,107,0\.82\)$/);
    expect(colors[2]).toMatch(/^rgba\(154,160,168,0\.\d+\)$/);
  });
  it('sums residents per bin', () => {
    const shares = binTotals(acc([300, 2000, null], [100, 300, 0]), 'gap', 'hospital', 'light');
    expect(shares[0]).toBeCloseTo(0.25);
    expect(shares[1]).toBeCloseTo(0.75);
  });
});

describe('helpers', () => {
  it('reads the concentration index with a ±0.03 dead band', () => {
    expect(readConcentration(0.08)).toBe('higher');
    expect(readConcentration(-0.07)).toBe('lower');
    expect(readConcentration(0.01)).toBe('similar');
    expect(readConcentration(undefined)).toBeNull();
  });
  it('interpolates the cumulative curve from the origin', () => {
    const curve: [number, number][] = [
      [600, 0.2],
      [1200, 0.6],
    ];
    expect(curvePoints(curve)[0]).toEqual([0, 0]);
    expect(shareAt(curve, 300)).toBeCloseTo(0.1);
    expect(shareAt(curve, 900)).toBeCloseTo(0.4);
    expect(shareAt(curve, 5000)).toBe(0.6);
  });
  it('orders essential categories first', () => {
    const ids = sortCategories([{ id: 'supermarket' }, { id: 'x' }, { id: 'hospital' }]).map(
      (c) => c.id,
    );
    expect(ids).toEqual(['hospital', 'supermarket', 'x']);
  });
});
