/**
 * Pure helpers for the optimizer view: stage list, explanation ranking, budget maths, chart
 * scales and the "diminishing returns" reading of the trade-off curve. No React, no MapLibre:
 * unit-tested in model.test.ts.
 */
import type {
  ExplanationItem,
  JobHistoryPoint,
  OptimizerMove,
  TradeoffPoint,
  TradeoffResult,
} from '@/api/optimizer';
import type { Theme } from '@/app/store';
import { DIVERGING } from '@/lib/palettes';

// ------------------------------------------------------------------ budget

/** Budget slider: percentage change versus today, in 5 % steps. */
export const BUDGET_PCT_MIN = -20;
export const BUDGET_PCT_MAX = 20;
export const BUDGET_PCT_STEP = 5;
/** The seven budgets of the trade-off curve (percent vs today). */
export const TRADEOFF_PCTS = [-20, -10, -5, 0, 5, 10, 20] as const;

/** Resource value for a percentage of today's budget (whole buses; bus-hours to 0.5). */
export function budgetValue(today: number, pct: number, kind: 'fleet' | 'bus_hours'): number {
  const raw = today * (1 + pct / 100);
  return kind === 'fleet' ? Math.round(raw) : Math.round(raw * 2) / 2;
}

// ------------------------------------------------------------------ stages

export type StageId = 'baseline' | 'stops' | 'probe' | 'milp' | 'alns' | 'local' | 'final' | 'done';

/** Server stage strings (docs/api.md and `log`) → stage id. */
export function stageId(stage: string): StageId | null {
  const s = stage.toLowerCase();
  if (s.startsWith('baseline')) return 'baseline';
  if (s.includes('stop')) return 'stops';
  if (s.includes('probing')) return 'probe';
  if (s.includes('milp') || s.includes('knapsack')) return 'milp';
  if (s.includes('alns') || s.includes('new line')) return 'alns';
  if (s.includes('local')) return 'local';
  if (s.includes('final')) return 'final';
  if (s === 'done') return 'done';
  return null;
}

/** Stages shown for a given set of moves, in execution order. */
export function stagesFor(moves: readonly OptimizerMove[]): StageId[] {
  const out: StageId[] = ['baseline'];
  if (moves.includes('stops')) out.push('stops');
  out.push('probe', 'milp');
  if (moves.includes('new_lines')) out.push('alns');
  out.push('local', 'final');
  return out;
}

export type StageState = 'done' | 'active' | 'pending';

/** State of each stage given the job's current stage (unknown stage: the first one is active). */
export function stageStates(
  stages: readonly StageId[],
  current: string,
  finished: boolean,
): { id: StageId; state: StageState }[] {
  const cur = stageId(current);
  let idx = cur === null ? 0 : stages.indexOf(cur);
  if (cur === 'done' || finished) idx = stages.length;
  if (idx < 0) idx = 0;
  return stages.map((id, i) => ({
    id,
    state: i < idx ? 'done' : i === idx ? 'active' : 'pending',
  }));
}

// ------------------------------------------------------------------ explanation

export interface FrequencyChange {
  route: string;
  routeId: string;
  fromMin: number;
  toMin: number;
  up: boolean;
  /** buses (or bus-hours) used (+) or freed (-) */
  resource: number;
  resourceKind: string;
  contribution: number;
}

const num = (v: unknown, d = 0) => (typeof v === 'number' && Number.isFinite(v) ? v : d);

/** Decode a frequency explanation item into display numbers (headways in whole minutes). */
export function frequencyChange(item: ExplanationItem): FrequencyChange {
  const from = num(item.params.from_headway);
  const to = num(item.params.to_headway);
  return {
    route: String(item.params.route ?? item.route_id ?? ''),
    routeId: item.route_id ?? '',
    fromMin: Math.round(from / 60),
    toMin: Math.round(to / 60),
    up: item.text_key === 'frequency_up' || to < from,
    resource: num(item.params.resource_delta),
    resourceKind: String(item.params.resource ?? 'fleet'),
    contribution: item.delta_objective,
  };
}

/** Explanation ranked by the size of the contribution (largest effect first, stable). */
export function rankExplanation(items: readonly ExplanationItem[]): ExplanationItem[] {
  return items
    .map((it, i) => ({ it, i }))
    .sort((a, b) => Math.abs(b.it.delta_objective) - Math.abs(a.it.delta_objective) || a.i - b.i)
    .map((x) => x.it);
}

export interface ExplanationGroups {
  lines: ExplanationItem[];
  stops: ExplanationItem[];
  newLines: ExplanationItem[];
}

export function groupExplanation(items: readonly ExplanationItem[]): ExplanationGroups {
  const ranked = rankExplanation(items);
  return {
    lines: ranked.filter((i) => i.kind === 'frequency'),
    stops: ranked.filter((i) => i.kind === 'stop'),
    newLines: ranked.filter((i) => i.kind === 'new_line'),
  };
}

/** Largest |contribution| among items, to scale the little bars (never 0). */
export const maxContribution = (items: readonly ExplanationItem[]) =>
  items.reduce((m, i) => Math.max(m, Math.abs(i.delta_objective)), 1e-9);

// ------------------------------------------------------------------ map diff

export type LineChange = 'up' | 'down' | 'same' | 'new';

/**
 * Width multiplier and class of a line from its change in trips: more trips → thicker, fewer →
 * thinner, bounded so a halved line stays visible and a doubled one does not swallow the map.
 */
export function lineChange(
  tripsBefore: number,
  tripsAfter: number,
): { kind: LineChange; scale: number } {
  if (!(tripsBefore > 0)) return { kind: 'new', scale: 1.4 };
  const ratio = tripsAfter / tripsBefore;
  if (ratio > 1.04) return { kind: 'up', scale: Math.min(2.1, ratio) };
  if (ratio < 0.96) return { kind: 'down', scale: Math.max(0.45, ratio) };
  return { kind: 'same', scale: 1 };
}

/** Travel-time changes below this magnitude are not drawn (noise). */
export const DELTA_MIN_S = 30;

/** Diverging colour for a change in mean travel time (s): blue = faster, red = slower. */
export function deltaTimeColor(dt: number | null, theme: Theme): string | null {
  if (dt === null || !Number.isFinite(dt) || Math.abs(dt) < DELTA_MIN_S) return null;
  const p = DIVERGING[theme];
  const m = Math.abs(dt);
  const step = m < 90 ? 0 : m < 180 ? 1 : 2; // weak, mid, strong
  return dt < 0 ? p.pos[step]! : p.neg[2 - step]!;
}

export const DELTA_LEGEND_STEPS = [-180, -90, -30, 30, 90, 180] as const;

// ------------------------------------------------------------------ charts

export interface LinearScale {
  (v: number): number;
  domain: [number, number];
  range: [number, number];
  invert: (px: number) => number;
}

export function linearScale(domain: [number, number], range: [number, number]): LinearScale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  const f = ((v: number) => r0 + (v - d0) * k) as LinearScale;
  f.domain = domain;
  f.range = range;
  f.invert = (px) => (k === 0 ? d0 : d0 + (px - r0) / k);
  return f;
}

/** "Nice" tick values covering [min, max] with about `count` ticks. */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!(max > min)) return [min];
  const rawStep = (max - min) / Math.max(1, count);
  const pow = 10 ** Math.floor(Math.log10(rawStep));
  const err = rawStep / pow;
  const step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * pow;
  const first = Math.ceil(min / step - 1e-9) * step;
  const out: number[] = [];
  for (let v = first; v <= max + step * 1e-9; v += step) out.push(Math.round(v / step) * step + 0);
  return out;
}

/** Padded y-domain that always contains 0 (today's network sits at 0 %). */
export function yDomain(values: readonly number[]): [number, number] {
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const pad = Math.max(0.4, (hi - lo) * 0.12);
  return [lo - pad, hi + pad];
}

export interface HistoryPlot {
  x: number[];
  y: number[];
}

/** Optimisation trace as % over its first value (the starting network), one point per eval. */
export function historySeries(history: readonly JobHistoryPoint[]): HistoryPlot {
  if (!history.length) return { x: [], y: [] };
  const base = history[0]!.objective || 1;
  const seen = new Set<string>();
  const x: number[] = [];
  const y: number[] = [];
  for (const h of history) {
    const key = `${h.iter}|${h.objective}`;
    if (seen.has(key)) continue;
    seen.add(key);
    x.push(h.iter);
    y.push((h.objective / base - 1) * 100);
  }
  return { x, y };
}

// ------------------------------------------------------------------ trade-off reading

export interface TradeoffReading {
  /** gain (% vs today) when the budget is the same as today's, null if no such point */
  sameBudgetGain: number | null;
  /** smallest budget whose optimised network is at least as good as today's */
  breakEven: { budget: number; savedPct: number } | null;
  /** marginal gain per +1 % of budget: first vs second half above today */
  marginal: { first: number; second: number } | null;
  diminishing: boolean;
}

export function readTradeoff(result: TradeoffResult): TradeoffReading {
  const today = result.baseline.budget;
  const pts = [...result.points].sort((a, b) => a.budget - b.budget);
  const same = pts.find((p) => Math.abs(p.budget - today) < 1e-6) ?? null;
  const ok = pts.filter((p) => p.objective_pct >= -0.05 && p.budget < today);
  const be = ok.length ? ok[0]! : null;
  const above = pts.filter((p) => p.budget > today);
  let marginal: TradeoffReading['marginal'] = null;
  if (above.length >= 2 && same) {
    const mid = above[Math.floor((above.length - 1) / 2)]!;
    const last = above[above.length - 1]!;
    const pct = (p: TradeoffPoint, q: TradeoffPoint) =>
      (q.budget - p.budget) / today > 0
        ? (q.objective_pct - p.objective_pct) / (((q.budget - p.budget) / today) * 100)
        : 0;
    marginal = { first: pct(same, mid), second: pct(mid, last) };
  }
  return {
    sameBudgetGain: same ? same.objective_pct : null,
    breakEven: be ? { budget: be.budget, savedPct: (1 - be.budget / today) * 100 } : null,
    marginal,
    diminishing: !!marginal && marginal.first > 0 && marginal.second < marginal.first * 0.75,
  };
}

// ------------------------------------------------------------------ misc

/** Stable key of a request, to decide whether a stored result still answers the form. */
export const cacheKey = (parts: unknown[]) => JSON.stringify(parts);
