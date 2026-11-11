import { describe, expect, it } from 'vitest';
import type { ExplanationItem, TradeoffResult } from '@/api/optimizer';
import {
  budgetValue,
  deltaTimeColor,
  frequencyChange,
  groupExplanation,
  historySeries,
  lineChange,
  linearScale,
  niceTicks,
  rankExplanation,
  readTradeoff,
  stageId,
  stageStates,
  stagesFor,
  yDomain,
} from './model';

const freq = (route: string, from: number, to: number, d: number, res = 0): ExplanationItem => ({
  kind: 'frequency',
  route_id: route,
  text_key: to < from ? 'frequency_up' : 'frequency_down',
  params: {
    route: `L${route}`,
    from_headway: from,
    to_headway: to,
    resource_delta: res,
    resource: 'fleet',
  },
  delta_objective: d,
});

describe('budget', () => {
  it('rounds buses to whole numbers and bus-hours to half hours', () => {
    expect(budgetValue(162, 0, 'fleet')).toBe(162);
    expect(budgetValue(162, -10, 'fleet')).toBe(146);
    expect(budgetValue(1234.4, 5, 'bus_hours')).toBe(1296);
  });
});

describe('stages', () => {
  it('maps the server stage strings', () => {
    expect(stageId('baseline')).toBe('baseline');
    expect(stageId('stop consolidation')).toBe('stops');
    expect(stageId('probing lines')).toBe('probe');
    expect(stageId('frequency MILP')).toBe('milp');
    expect(stageId('new lines (ALNS)')).toBe('alns');
    expect(stageId('local search')).toBe('local');
    expect(stageId('final evaluation')).toBe('final');
    expect(stageId('whatever')).toBeNull();
  });
  it('only lists the stages the chosen moves use', () => {
    expect(stagesFor(['frequency'])).toEqual(['baseline', 'probe', 'milp', 'local', 'final']);
    expect(stagesFor(['frequency', 'stops', 'new_lines'])).toEqual([
      'baseline',
      'stops',
      'probe',
      'milp',
      'alns',
      'local',
      'final',
    ]);
  });
  it('ticks finished stages and marks the current one', () => {
    const st = stageStates(stagesFor(['frequency']), 'frequency MILP', false);
    expect(st.map((s) => s.state)).toEqual(['done', 'done', 'active', 'pending', 'pending']);
    expect(
      stageStates(stagesFor(['frequency']), 'done', true).every((s) => s.state === 'done'),
    ).toBe(true);
  });
});

describe('explanation', () => {
  const items = [
    freq('1', 600, 900, -0.001),
    freq('16', 657, 438, 0.0008, 8),
    freq('10', 1800, 900, 0.0006),
  ];
  it('ranks by absolute contribution', () => {
    expect(rankExplanation(items).map((i) => i.route_id)).toEqual(['1', '16', '10']);
  });
  it('decodes headways in minutes and direction', () => {
    const c = frequencyChange(items[1]!);
    expect(c).toMatchObject({ route: 'L16', fromMin: 11, toMin: 7, up: true, resource: 8 });
    expect(frequencyChange(items[0]!).up).toBe(false);
  });
  it('groups by kind', () => {
    const g = groupExplanation([
      ...items,
      { kind: 'stop', route_id: null, text_key: 'stop_removed', params: {}, delta_objective: 0 },
    ]);
    expect(g.lines).toHaveLength(3);
    expect(g.stops).toHaveLength(1);
    expect(g.newLines).toHaveLength(0);
  });
});

describe('map diff', () => {
  it('classifies lines by their change in trips', () => {
    expect(lineChange(100, 100)).toEqual({ kind: 'same', scale: 1 });
    expect(lineChange(100, 150)).toEqual({ kind: 'up', scale: 1.5 });
    expect(lineChange(100, 400).scale).toBe(2.1);
    expect(lineChange(100, 50)).toEqual({ kind: 'down', scale: 0.5 });
    expect(lineChange(100, 10).scale).toBe(0.45);
    expect(lineChange(0, 40).kind).toBe('new');
  });
  it('colours only meaningful travel-time changes, blue for faster', () => {
    expect(deltaTimeColor(null, 'light')).toBeNull();
    expect(deltaTimeColor(12, 'light')).toBeNull();
    expect(deltaTimeColor(-45, 'light')).not.toBe(deltaTimeColor(-200, 'light'));
    expect(deltaTimeColor(-100, 'light')).not.toBe(deltaTimeColor(100, 'light'));
  });
});

describe('scales', () => {
  it('maps domain to range and back', () => {
    const s = linearScale([0, 10], [100, 300]);
    expect(s(0)).toBe(100);
    expect(s(5)).toBe(200);
    expect(s.invert(300)).toBe(10);
  });
  it('is safe on a degenerate domain', () => {
    const s = linearScale([3, 3], [0, 100]);
    expect(s(3)).toBe(0);
    expect(s.invert(50)).toBe(3);
  });
  it('produces nice ticks', () => {
    expect(niceTicks(0, 10, 5)).toEqual([0, 2, 4, 6, 8, 10]);
    expect(niceTicks(-1.2, 3.1, 4)).toEqual([-1, 0, 1, 2, 3]);
    expect(niceTicks(5, 5)).toEqual([5]);
  });
  it('always includes zero in the y domain', () => {
    const [lo, hi] = yDomain([1.2, 3.4]);
    expect(lo).toBeLessThan(0);
    expect(hi).toBeGreaterThan(3.4);
  });
  it('turns the history into percent over the start, dropping repeats', () => {
    const h = historySeries([
      { iter: 1, objective: 0.05, used: 162 },
      { iter: 10, objective: 0.0505, used: 160 },
      { iter: 10, objective: 0.0505, used: 160 },
    ]);
    expect(h.x).toEqual([1, 10]);
    expect(h.y[0]).toBeCloseTo(0);
    expect(h.y[1]).toBeCloseTo(1);
  });
});

describe('trade-off reading', () => {
  const mk = (pcts: number[], today = 100): TradeoffResult => ({
    budget_kind: 'fleet',
    baseline: { budget: today, objective: 1, mean_travel_time: 900, share_within: {} },
    points: pcts.map((p, i) => ({
      budget: today * (1 + (i - 2) / 10),
      used: today * (1 + (i - 2) / 10),
      objective: 1,
      objective_pct: p,
      mean_travel_time: 900,
      share_within: {},
      scenario: [],
    })),
  });
  it('finds the same-budget gain, the break-even budget and diminishing returns', () => {
    const r = readTradeoff(mk([-1, 0.2, 3, 5, 5.6]));
    expect(r.sameBudgetGain).toBe(3);
    expect(r.breakEven?.budget).toBeCloseTo(90);
    expect(r.breakEven?.savedPct).toBeCloseTo(10);
    expect(r.diminishing).toBe(true);
  });
  it('does not claim diminishing returns for a straight line', () => {
    const r = readTradeoff(mk([-4, -2, 0, 2, 4]));
    expect(r.diminishing).toBe(false);
    expect(r.breakEven).toBeNull();
  });
});
