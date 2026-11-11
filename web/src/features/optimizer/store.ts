/**
 * Optimizer state (zustand). Jobs run on the server one at a time; the store polls them, so a
 * computation keeps going while the user looks at another view. The settings, the last result
 * and the last trade-off curve are persisted to localStorage so a reload never loses a long
 * computation (the result is plain JSON).
 */
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import {
  optimizerApi,
  type BudgetKind,
  type Job,
  type JobHistoryPoint,
  type JobLogLine,
  type OptimizeRequest,
  type OptimizeResult,
  type OptimizerMove,
  type OptimizerObjective,
  type TradeoffRequest,
  type TradeoffResult,
} from '@/api/optimizer';
import type { AnalysisWindow, Edit } from '@/api/types';
import { TRADEOFF_PCTS, budgetValue } from './model';

export type TimeLimit = 30 | 60 | 120;

export interface OptSettings {
  budgetKind: BudgetKind;
  /** percent change of the budget vs today, 0 = same as today */
  budgetPct: number;
  moves: Record<OptimizerMove, boolean>;
  objective: OptimizerObjective;
  timeLimit: TimeLimit;
  /** start from the scenario in the scenario store */
  fromScenario: boolean;
}

export const DEFAULT_SETTINGS: OptSettings = {
  budgetKind: 'fleet',
  budgetPct: 0,
  moves: { frequency: true, stops: false, new_lines: false },
  objective: 'accessibility',
  timeLimit: 60,
  fromScenario: false,
};

export const THRESHOLD = 1800;

export interface RunState {
  phase: 'idle' | 'running' | 'error';
  status: 'queued' | 'running';
  progress: number;
  stage: string;
  log: JobLogLine[];
  history: JobHistoryPoint[];
  error: string | null;
  startedAt: number;
  /** the user cancelled: the server keeps computing in the background */
  cancelled: boolean;
}

const IDLE_RUN: RunState = {
  phase: 'idle',
  status: 'queued',
  progress: 0,
  stage: '',
  log: [],
  history: [],
  error: null,
  startedAt: 0,
  cancelled: false,
};

export interface StoredResult {
  result: OptimizeResult;
  window: AnalysisWindow;
  moves: OptimizerMove[];
  objective: OptimizerObjective;
  /** today's budget in the unit of `result.budget.kind` (for the sentence "same N buses") */
  today: number;
  fromScenario: boolean;
  createdAt: number;
}

export interface StoredTradeoff {
  result: TradeoffResult;
  window: AnalysisWindow;
  createdAt: number;
}

export interface TradeState {
  phase: 'idle' | 'running' | 'error';
  progress: number;
  error: string | null;
}

/** What the map shows: the optimizer result, or the scenario of one trade-off point. */
export type Preview = { kind: 'result' } | { kind: 'point'; budget: number };

export interface OptimizerState {
  settings: OptSettings;
  run: RunState;
  last: StoredResult | null;
  tradeoff: StoredTradeoff | null;
  trade: TradeState;
  preview: Preview;
  /** line (route id) highlighted from the explanation list */
  focusRoute: string | null;
  focusStop: string | null;
  /** increments to replay the reveal animation */
  revealKey: number;
}

export interface OptimizerActions {
  setSettings: (patch: Partial<OptSettings>) => void;
  start: (args: {
    window: AnalysisWindow;
    today: number;
    base: Edit[] | null;
    seed?: number;
  }) => Promise<void>;
  cancel: () => void;
  startTradeoff: (args: { window: AnalysisWindow; today: number }) => Promise<void>;
  setPreview: (p: Preview) => void;
  setFocus: (route: string | null, stop?: string | null) => void;
  replay: () => void;
  discard: () => void;
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

let runToken = 0;
let tradeToken = 0;

const messageOf = (e: unknown) => (e instanceof Error && e.message ? e.message : 'error');

/** Poll a job until it finishes. Calls `onJob` with every snapshot. */
async function pollJob<R>(
  id: string,
  token: () => boolean,
  onJob: (job: Job<R>) => void,
): Promise<Job<R> | null> {
  let failures = 0;
  for (;;) {
    if (token()) return null;
    try {
      const job = await optimizerApi.job<R>(id);
      failures = 0;
      if (token()) return null;
      onJob(job);
      if (job.status === 'done' || job.status === 'error') return job;
    } catch (e) {
      failures += 1;
      if (failures >= 4) throw e;
    }
    await sleep(700);
  }
}

export const useOptimizer = create<OptimizerState & OptimizerActions>()(
  persist(
    (set, get) => ({
      settings: DEFAULT_SETTINGS,
      run: IDLE_RUN,
      last: null,
      tradeoff: null,
      trade: { phase: 'idle', progress: 0, error: null },
      preview: { kind: 'result' },
      focusRoute: null,
      focusStop: null,
      revealKey: 0,

      setSettings: (patch) => set((s) => ({ settings: { ...s.settings, ...patch } })),

      start: async ({ window, today, base, seed = 0 }) => {
        const { settings } = get();
        const moves = (Object.keys(settings.moves) as OptimizerMove[]).filter(
          (m) => settings.moves[m],
        );
        if (!moves.length) return;
        const token = ++runToken;
        const cancelled = () => token !== runToken;
        const useBase = settings.fromScenario && !!base?.length;
        const body: OptimizeRequest = {
          window,
          budget: {
            kind: settings.budgetKind,
            value:
              settings.budgetPct === 0
                ? null
                : budgetValue(today, settings.budgetPct, settings.budgetKind),
          },
          moves,
          objective: settings.objective,
          base_scenario: useBase ? base : null,
          seed,
          time_limit_s: settings.timeLimit,
          threshold: THRESHOLD,
        };
        set({
          run: { ...IDLE_RUN, phase: 'running', startedAt: Date.now() },
          focusRoute: null,
          focusStop: null,
        });
        try {
          const { job_id } = await optimizerApi.start(body);
          const patch = (job: Job<OptimizeResult>) => {
            if (cancelled()) return;
            set((s) => ({
              run: {
                ...s.run,
                status: job.status === 'queued' ? 'queued' : 'running',
                progress: job.progress,
                stage: job.stage,
                log: job.log,
                history: job.history,
              },
            }));
          };
          const job = await pollJob<OptimizeResult>(job_id, cancelled, patch);
          if (!job || cancelled()) return;
          if (job.status === 'done' && job.result) {
            set((s) => ({
              run: IDLE_RUN,
              last: {
                result: job.result as OptimizeResult,
                window,
                moves,
                objective: settings.objective,
                today,
                fromScenario: useBase,
                createdAt: Date.now(),
              },
              preview: { kind: 'result' },
              revealKey: s.revealKey + 1,
              // a new proposal makes an older curve (computed for other settings) stale
              tradeoff: s.tradeoff,
            }));
          } else {
            set((s) => ({
              run: { ...s.run, phase: 'error', error: job.error ?? 'error' },
            }));
          }
        } catch (e) {
          if (cancelled()) return;
          set((s) => ({ run: { ...s.run, phase: 'error', error: messageOf(e) } }));
        }
      },

      cancel: () => {
        runToken++;
        set((s) => ({ run: { ...s.run, phase: 'idle', cancelled: true } }));
      },

      startTradeoff: async ({ window, today }) => {
        const { settings } = get();
        const token = ++tradeToken;
        const cancelled = () => token !== tradeToken;
        const body: TradeoffRequest = {
          window,
          budget_kind: settings.budgetKind,
          values: TRADEOFF_PCTS.map((p) => budgetValue(today, p, settings.budgetKind)),
          seed: 0,
        };
        set({ trade: { phase: 'running', progress: 0, error: null } });
        try {
          const { job_id } = await optimizerApi.startTradeoff(body);
          const job = await pollJob<TradeoffResult>(job_id, cancelled, (j) => {
            if (!cancelled())
              set({ trade: { phase: 'running', progress: j.progress, error: null } });
          });
          if (!job || cancelled()) return;
          if (job.status === 'done' && job.result) {
            set({
              tradeoff: { result: job.result, window, createdAt: Date.now() },
              trade: { phase: 'idle', progress: 1, error: null },
            });
          } else {
            set({ trade: { phase: 'error', progress: 0, error: job.error ?? 'error' } });
          }
        } catch (e) {
          if (!cancelled()) set({ trade: { phase: 'error', progress: 0, error: messageOf(e) } });
        }
      },

      setPreview: (preview) => set((s) => ({ preview, revealKey: s.revealKey + 1 })),
      setFocus: (focusRoute, focusStop = null) => set({ focusRoute, focusStop }),
      replay: () => set((s) => ({ revealKey: s.revealKey + 1 })),
      discard: () =>
        set({ last: null, preview: { kind: 'result' }, run: IDLE_RUN, focusRoute: null }),
    }),
    {
      name: 'vlab.optimizer.v1',
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({ settings: s.settings, last: s.last, tradeoff: s.tradeoff }),
      merge: (persisted, current) => {
        const p = (persisted ?? {}) as Partial<OptimizerState>;
        return {
          ...current,
          settings: { ...DEFAULT_SETTINGS, ...(p.settings ?? {}) },
          last: p.last?.result?.scenario ? p.last : null,
          tradeoff: p.tradeoff?.result?.points ? p.tradeoff : null,
        };
      },
    },
  ),
);

/** The scenario of the point being previewed (null = the optimizer result itself). */
export function previewedPoint(s: OptimizerState) {
  if (s.preview.kind !== 'point' || !s.tradeoff) return null;
  const b = s.preview.budget;
  return s.tradeoff.result.points.find((p) => p.budget === b) ?? null;
}
