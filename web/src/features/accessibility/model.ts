/**
 * Pure helpers for the accessibility view: per-zone metric values, binning, colours and the
 * weights that keep sparsely populated cells from dominating the map. No React, no MapLibre:
 * unit-tested in model.test.ts.
 */
import type { Accessibility } from '@/api/types';
import type { AccMetric, Theme } from '@/app/store';
import { DIVERGING, SEQUENTIAL_BLUE } from '@/lib/palettes';

/** Display order of destination categories (essential ones first). */
export const CATEGORY_ORDER = [
  'hospital',
  'health_centre',
  'city_centre',
  'university',
  'industrial_estate',
  'secondary_school',
  'supermarket',
] as const;

export const sortCategories = <T extends { id: string }>(cats: T[]): T[] =>
  [...cats].sort((a, b) => rank(a.id) - rank(b.id));
const rank = (id: string) => {
  const i = (CATEGORY_ORDER as readonly string[]).indexOf(id);
  return i < 0 ? 99 : i;
};

/** Neutral grey for "no value" (unreachable, no income data): distinct from every ramp step. */
export const NO_DATA: Record<Theme, string> = { light: '#9aa0a8', dark: '#5d636c' };
/** "Within the threshold" in the under-served view: quiet neutral so failing cells pop. */
const WITHIN: Record<Theme, string> = { light: '#c9cdd2', dark: '#3a3e45' };

export type BinKind = 'value' | 'none';
export interface Bin {
  color: string;
  /** lower edge (inclusive) in metric units; -Infinity for the first bin */
  from: number;
  /** upper edge (exclusive); Infinity for the last bin */
  to: number;
  kind: BinKind;
}

export interface MetricScale {
  bins: Bin[];
  /** bin index for a raw value (null → the "none" bin) */
  binOf: (v: number | null) => number;
}

/** Sequential ramp oriented so "better" reads as more prominent on either basemap. */
function ramp(theme: Theme, n: number, highIsGood: boolean): string[] {
  // 7 light→dark steps; drop the palest step when fewer bins are needed
  const steps = SEQUENTIAL_BLUE.slice(SEQUENTIAL_BLUE.length - n);
  // light map: darker = more prominent; dark map: lighter = more prominent (as in isochrones)
  const prominentLast = theme === 'light';
  const ordered = prominentLast ? [...steps] : [...steps].reverse();
  // ordered[i] grows in prominence with i; map "good" to prominent
  return highIsGood ? ordered : ordered.reverse();
}

function edgesScale(
  edges: number[],
  colors: string[],
  none: string | null,
  noneFirst = false,
): MetricScale {
  const bins: Bin[] = colors.map((color, i) => ({
    color,
    from: i === 0 ? -Infinity : edges[i - 1]!,
    to: i === colors.length - 1 ? Infinity : edges[i]!,
    kind: 'value',
  }));
  if (none) {
    const nb: Bin = { color: none, from: NaN, to: NaN, kind: 'none' };
    if (noneFirst) bins.unshift(nb);
    else bins.push(nb);
  }
  const off = none && noneFirst ? 1 : 0;
  const noneIdx = none ? (noneFirst ? 0 : bins.length - 1) : -1;
  return {
    bins,
    binOf: (v) => {
      if (v === null || !Number.isFinite(v)) return noneIdx;
      let i = 0;
      while (i < edges.length && v >= edges[i]!) i++;
      return off + Math.min(i, colors.length - 1);
    },
  };
}

/** Time bins: 10-minute steps to 60 min, then "more than 60", then unreachable. */
export const TIME_EDGES = [600, 1200, 1800, 2400, 3000, 3600];
export const JOBS_EDGES = [0.025, 0.05, 0.1, 0.15, 0.2, 0.25];
export const INCOME_EDGES = [15000, 16500, 18000, 19500, 21000, 23500];

export function metricScale(metric: AccMetric, theme: Theme, threshold: number): MetricScale {
  switch (metric) {
    case 'time':
      return edgesScale(TIME_EDGES, ramp(theme, 7, false), NO_DATA[theme]);
    case 'gap': {
      // within the threshold (neutral) → over by ≤ 10 min → 10–20 min → > 20 min or unreachable
      const neg = DIVERGING[theme].neg; // [strong, mid, soft]
      const s = edgesScale(
        [threshold, threshold + 600, threshold + 1200],
        [WITHIN[theme], neg[2]!, neg[1]!, neg[0]!],
        null,
      );
      return { bins: s.bins, binOf: (v) => (v === null ? 3 : s.binOf(v)) };
    }
    case 'jobs':
      return edgesScale(JOBS_EDGES, ramp(theme, 7, true), null);
    case 'income':
      return edgesScale(INCOME_EDGES, ramp(theme, 7, true), NO_DATA[theme]);
  }
}

/** Raw per-zone values of a metric, aligned with the zone index. */
export function metricValues(
  acc: Accessibility,
  metric: AccMetric,
  category: string,
): (number | null)[] {
  switch (metric) {
    case 'time':
    case 'gap':
      return acc.zones.time[category] ?? acc.zones.population.map(() => null);
    case 'jobs':
      return acc.zones.jobs_30;
    case 'income':
      return acc.zones.income;
  }
}

/**
 * Opacity weight of a cell by residents: hidden when empty, then a floor so small hamlets stay
 * legible, saturating at ~400 residents per 4 ha cell (a dense urban block).
 */
export function residentWeight(pop: number): number {
  if (!(pop > 0)) return 0;
  return 0.32 + 0.68 * Math.min(1, Math.sqrt(pop / 400));
}

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  const n = parseInt(
    h.length === 3
      ? h
          .split('')
          .map((c) => c + c)
          .join('')
      : h,
    16,
  );
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export const rgba = (hex: string, a: number) => {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r},${g},${b},${Math.round(a * 1000) / 1000})`;
};

/** Final per-zone fill colours (with alpha baked in), aligned with the zone index. */
export function zoneColors(
  acc: Accessibility,
  metric: AccMetric,
  category: string,
  theme: Theme,
): string[] {
  const scale = metricScale(metric, theme, acc.threshold);
  const values = metricValues(acc, metric, category);
  const maxAlpha = theme === 'dark' ? 0.78 : 0.82;
  return acc.zones.population.map((pop, i) => {
    const w = residentWeight(pop);
    if (w === 0) return 'rgba(0,0,0,0)';
    const bin = scale.bins[scale.binOf(values[i] ?? null)];
    return bin ? rgba(bin.color, w * maxAlpha) : 'rgba(0,0,0,0)';
  });
}

/** Residents and share of residents per bin (for the legend's distribution strip). */
export function binTotals(acc: Accessibility, metric: AccMetric, category: string, theme: Theme) {
  const scale = metricScale(metric, theme, acc.threshold);
  const values = metricValues(acc, metric, category);
  const totals = scale.bins.map(() => 0);
  let all = 0;
  acc.zones.population.forEach((pop, i) => {
    if (!(pop > 0)) return;
    const b = scale.binOf(values[i] ?? null);
    if (b >= 0) totals[b] = (totals[b] ?? 0) + pop;
    all += pop;
  });
  return totals.map((n) => (all ? n / all : 0));
}

/** Plain-language reading of a concentration index (positive = concentrated among the rich). */
export type EquityReading = 'higher' | 'lower' | 'similar';
export function readConcentration(ci: number | null | undefined): EquityReading | null {
  if (ci === null || ci === undefined || !Number.isFinite(ci)) return null;
  if (ci > 0.03) return 'higher';
  if (ci < -0.03) return 'lower';
  return 'similar';
}

/** Cumulative curve with an explicit origin at 0 min. */
export function curvePoints(curve: [number, number][]): [number, number][] {
  const pts = [...curve].sort((a, b) => a[0] - b[0]);
  return pts[0]?.[0] === 0 ? pts : [[0, 0], ...pts];
}

/** Share reached at `t` seconds by linear interpolation of the cumulative curve. */
export function shareAt(curve: [number, number][], t: number): number | null {
  const pts = curvePoints(curve);
  if (!pts.length) return null;
  for (let i = 1; i < pts.length; i++) {
    const [t1, s1] = pts[i]!;
    const [t0, s0] = pts[i - 1]!;
    if (t <= t1) return s0 + ((s1 - s0) * (t - t0)) / Math.max(1, t1 - t0);
  }
  return pts.at(-1)![1];
}
