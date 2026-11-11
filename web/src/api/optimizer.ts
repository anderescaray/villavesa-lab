/**
 * Optimizer and report endpoints (M10): `POST /api/optimize`, `GET /api/optimize/{id}`,
 * `POST /api/optimize/tradeoff` and `POST /api/report` (docs/api.md). Jobs run one at a time on
 * the server and are polled; the result is an ordinary edit list.
 */
import type { AnalysisWindow, Edit, Evaluation } from './types';
import { ApiError } from './client';

export type BudgetKind = 'fleet' | 'bus_hours';
export type OptimizerMove = 'frequency' | 'stops' | 'new_lines';
export type OptimizerObjective = 'accessibility' | 'travel_time';

export interface OptimizeRequest {
  window: AnalysisWindow;
  budget: { kind: BudgetKind; value: number | null };
  moves: OptimizerMove[];
  objective: OptimizerObjective;
  base_scenario: Edit[] | null;
  seed: number;
  time_limit_s: number;
  threshold: number;
}

export interface TradeoffRequest {
  window: AnalysisWindow;
  budget_kind: BudgetKind;
  values: number[];
  seed: number;
}

export type JobStatus = 'queued' | 'running' | 'done' | 'error';

export interface JobLogLine {
  t: number;
  msg: string;
}
export interface JobHistoryPoint {
  iter: number;
  objective: number;
  used: number;
}

export interface Job<R> {
  job_id: string;
  kind: string;
  status: JobStatus;
  progress: number;
  stage: string;
  log: JobLogLine[];
  history: JobHistoryPoint[];
  result: R | null;
  error: string | null;
}

export type ExplanationKind = 'frequency' | 'stop' | 'new_line';
export interface ExplanationItem {
  kind: ExplanationKind;
  route_id: string | null;
  text_key: 'frequency_up' | 'frequency_down' | 'stop_removed' | 'new_line' | string;
  params: Record<string, string | number>;
  delta_objective: number;
}

export interface OptimizeResult {
  scenario: Edit[];
  evaluation: Evaluation;
  explanation: ExplanationItem[];
  objective: { baseline: number; optimized: number; change_pct: number };
  budget: { kind: BudgetKind; value: number | null; used: number };
  elapsed_s: number;
}

export interface TradeoffPoint {
  budget: number;
  used: number;
  objective: number;
  objective_pct: number;
  mean_travel_time: number;
  share_within: Record<string, number>;
  scenario: Edit[];
}
export interface TradeoffResult {
  budget_kind: BudgetKind;
  points: TradeoffPoint[];
  baseline: {
    budget: number;
    objective: number;
    mean_travel_time: number;
    share_within: Record<string, number>;
  };
}

export interface ReportRequest {
  scenario: Edit[];
  window: AnalysisWindow;
  threshold: number;
  lang: 'es' | 'en';
  title: string;
}

async function send(path: string, init: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError(0, 'network');
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = (await res.json()) as { detail?: unknown };
      if (typeof j.detail === 'string') detail = j.detail;
      else if (Array.isArray(j.detail))
        detail = j.detail
          .map((d: { msg?: string }) => d?.msg)
          .filter(Boolean)
          .join('; ');
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res;
}

const postJson = async <T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> =>
  (
    await send(path, {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })
  ).json() as Promise<T>;

export const optimizerApi = {
  start: (body: OptimizeRequest, signal?: AbortSignal) =>
    postJson<{ job_id: string }>('/optimize', body, signal),
  startTradeoff: (body: TradeoffRequest, signal?: AbortSignal) =>
    postJson<{ job_id: string }>('/optimize/tradeoff', body, signal),
  job: async <R>(id: string, signal?: AbortSignal): Promise<Job<R>> =>
    (
      await send(`/optimize/${encodeURIComponent(id)}`, {
        headers: { Accept: 'application/json' },
        signal,
      })
    ).json() as Promise<Job<R>>,
  /** Self-contained print-ready HTML. */
  report: async (body: ReportRequest, signal?: AbortSignal): Promise<string> =>
    (
      await send('/report', {
        method: 'POST',
        headers: { Accept: 'text/html', 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal,
      })
    ).text(),
};
