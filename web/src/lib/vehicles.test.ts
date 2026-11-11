import { describe, expect, it } from 'vitest';
import type { Vehicles } from '@/api/types';
import {
  activeCount,
  buildVehicleIndex,
  computeFrame,
  createFrame,
  departuresByHour,
  distanceAt,
  headwayAround,
  lastLE,
  pointAlong,
} from './vehicles';

// A straight east-west shape 1 km long at the equator-ish (lat 0 → simple maths), and a
// north-going one.
const east = {
  id: 7,
  path: [
    [0, 0],
    [0.005, 0],
    [0.01, 0],
  ] as [number, number][],
  cum_m: [0, 500, 1000],
};
const north = {
  id: 9,
  path: [
    [0, 0],
    [0, 0.01],
  ] as [number, number][],
  cum_m: [0, 1000],
};

const fixture: Vehicles = {
  day: 'weekday',
  shapes: [east, north],
  trips: [
    // trip B listed first on purpose: index must sort by start
    { route: 'B', shape: 9, headsign: '', direction: 0, t: [200, 300], d: [0, 1000] },
    // dwell at 500 m between t=150 and t=170
    { route: 'A', shape: 7, headsign: '', direction: 0, t: [100, 150, 170, 220], d: [0, 500, 500, 1000] },
  ],
};

describe('lastLE', () => {
  it('finds the last index with value <= x', () => {
    const a = [1, 3, 3, 5];
    expect(lastLE(a, 0)).toBe(-1);
    expect(lastLE(a, 1)).toBe(0);
    expect(lastLE(a, 3)).toBe(2);
    expect(lastLE(a, 4)).toBe(2);
    expect(lastLE(a, 99)).toBe(3);
  });
});

describe('buildVehicleIndex', () => {
  const idx = buildVehicleIndex(fixture);
  it('sorts trips by start and records the domain', () => {
    expect(Array.from(idx.start)).toEqual([100, 200]);
    expect(Array.from(idx.end)).toEqual([220, 300]);
    expect(idx.domain).toEqual([100, 300]);
    expect(idx.routeIds[idx.routeOf[0]!]).toBe('A');
    expect(idx.maxDuration).toBe(120);
  });
  it('maps shape ids (not array positions)', () => {
    expect(idx.shapeOf[0]).toBe(0);
    expect(idx.shapeOf[1]).toBe(1);
  });
  it('repairs decreasing times defensively', () => {
    const bad = buildVehicleIndex({
      day: 'weekday',
      shapes: [east],
      trips: [{ route: 'X', shape: 7, headsign: '', direction: 0, t: [10, 5, 20], d: [0, 100, 50] }],
    });
    expect(Array.from(bad.t)).toEqual([10, 10, 20]);
    expect(Array.from(bad.d)).toEqual([0, 100, 100]);
  });
});

describe('distanceAt', () => {
  const idx = buildVehicleIndex(fixture);
  it('interpolates linearly between waypoints', () => {
    expect(distanceAt(idx, 0, 125)).toBeCloseTo(250);
    expect(distanceAt(idx, 0, 195)).toBeCloseTo(750);
  });
  it('holds position while dwelling (equal distances)', () => {
    expect(distanceAt(idx, 0, 160)).toBe(500);
  });
  it('clamps outside the trip', () => {
    expect(distanceAt(idx, 0, 0)).toBe(0);
    expect(distanceAt(idx, 0, 9999)).toBe(1000);
  });
  it('handles repeated timestamps (zero-duration segment)', () => {
    const z = buildVehicleIndex({
      day: 'weekday',
      shapes: [east],
      trips: [{ route: 'Z', shape: 7, headsign: '', direction: 0, t: [0, 10, 10, 20], d: [0, 100, 200, 300] }],
    });
    expect(distanceAt(z, 0, 10)).toBe(200);
  });
});

describe('pointAlong', () => {
  const idx = buildVehicleIndex(fixture);
  const out = [0, 0, 0];
  it('returns position and bearing (east = 90°)', () => {
    pointAlong(idx.shapes[0]!, 250, out);
    expect(out[0]).toBeCloseTo(0.0025);
    expect(out[1]).toBeCloseTo(0);
    expect(out[2]).toBeCloseTo(90);
  });
  it('north = 0°', () => {
    pointAlong(idx.shapes[1]!, 500, out);
    expect(out[1]).toBeCloseTo(0.005);
    expect(out[2]).toBeCloseTo(0);
  });
  it('clamps beyond the ends', () => {
    pointAlong(idx.shapes[0]!, -50, out);
    expect(out[0]).toBeCloseTo(0);
    pointAlong(idx.shapes[0]!, 5000, out);
    expect(out[0]).toBeCloseTo(0.01);
  });
  it('copes with degenerate shapes', () => {
    pointAlong({ coords: new Float64Array([1, 2]), cum: new Float64Array([0]) }, 10, out);
    expect(out).toEqual([1, 2, 0]);
  });
});

describe('computeFrame / activeCount', () => {
  const idx = buildVehicleIndex(fixture);
  const frame = createFrame(8);
  it('includes only trips in service (inclusive bounds)', () => {
    expect(computeFrame(idx, 50, frame)).toBe(0);
    expect(computeFrame(idx, 100, frame)).toBe(1);
    expect(computeFrame(idx, 210, frame)).toBe(2);
    expect(computeFrame(idx, 300, frame)).toBe(1);
    expect(computeFrame(idx, 301, frame)).toBe(0);
    expect(activeCount(idx, 210)).toBe(2);
  });
  it('writes positions for each active vehicle', () => {
    computeFrame(idx, 250, frame);
    expect(frame.count).toBe(1);
    expect(frame.positions[0]).toBeCloseTo(0);
    expect(frame.positions[1]).toBeCloseTo(0.005);
    expect(idx.routeIds[frame.route[0]!]).toBe('B');
  });
  it('never overflows the frame capacity', () => {
    const small = createFrame(1);
    expect(computeFrame(idx, 210, small)).toBe(1);
  });
});

describe('departuresByHour / headwayAround', () => {
  it('buckets departures by service hour', () => {
    const trips = Array.from({ length: 12 }, (_, i) => ({
      route: 'A',
      shape: 7,
      headsign: '',
      direction: 0,
      t: [8 * 3600 + i * 300, 8 * 3600 + i * 300 + 600],
      d: [0, 1000],
    }));
    const idx = buildVehicleIndex({ day: 'weekday', shapes: [east], trips });
    const per = departuresByHour(idx);
    expect(per.get('A')?.[8]).toBe(12);
    // 12 departures/h in one direction → every 5 min (smoothed with empty neighbours: 6/h)
    expect(headwayAround([...Array(7).fill(0), 12, 12, 12], 8.5 * 3600, 1)).toBe(300);
    expect(headwayAround(per.get('A'), 8.5 * 3600, 1)).toBe(600);
    expect(headwayAround(undefined, 0)).toBeNull();
    expect(headwayAround([0, 0, 0], 3600)).toBeNull();
  });
});
