/**
 * Scenario-editor endpoints (M8): `/api/scenario/evaluate` and `/api/scenario/snap`, plus the
 * exact wire format of every edit the editor produces. The edit types here are refinements of
 * `Edit` in `types.ts` (every `ScenarioEdit` is assignable to `Edit`), adding the optional fields
 * the server accepts (`period` on `scale_frequency`, `route_id` on `remove_stop`).
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { ApiError } from './client';
import type { AnalysisWindow, Edit, Evaluation, LonLat } from './types';

export type Period = 'all' | 'peak' | 'offpeak';

export type SetHeadwayEdit = {
  type: 'set_headway';
  route_id: string;
  headway: number;
  period: Period;
};
export type ScaleFrequencyEdit = {
  type: 'scale_frequency';
  route_id: string;
  factor: number;
  period?: Period;
};
export type SpeedUpEdit = {
  type: 'speed_up';
  route_id: string | null;
  stop_ids: string[];
  factor: number;
};
export type RemoveStopEdit = { type: 'remove_stop'; stop_id: string; route_id?: string };
export type MoveStopEdit = { type: 'move_stop'; stop_id: string; lon: number; lat: number };
export type AddStopEdit = {
  type: 'add_stop';
  stop_id: string;
  name: string;
  lon: number;
  lat: number;
  route_id: string;
  direction: number;
  after_stop_id: string;
};
export type RemoveRouteEdit = { type: 'remove_route'; route_id: string };
export type RouteStopRef = { stop_id: string } | { lon: number; lat: number; name: string };
export type AddRouteEdit = {
  type: 'add_route';
  route_id: string;
  short_name: string;
  color: string;
  waypoints: LonLat[];
  stops: RouteStopRef[];
  headway: number;
  bidirectional: boolean;
  speed_kmh: number | null;
};

export type ScenarioEdit =
  | SetHeadwayEdit
  | ScaleFrequencyEdit
  | SpeedUpEdit
  | RemoveStopEdit
  | MoveStopEdit
  | AddStopEdit
  | RemoveRouteEdit
  | AddRouteEdit;

/** Compile-time guarantee that the editor's edits are valid `Edit`s for the shared hooks. */
export const asEdits = (edits: readonly ScenarioEdit[]): Edit[] => edits as Edit[];

export const HEADWAY_MIN_S = 120;
export const HEADWAY_MAX_S = 7200;

export interface SnapResponse {
  path: LonLat[];
  length_m: number;
  nearby_stops: { id: string; name: string; offset_m: number; distance_m: number }[];
  warnings: string[];
}

async function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });
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
  return (await res.json()) as T;
}

export const scenarioApi = {
  evaluate: (
    body: { scenario: ScenarioEdit[]; window: AnalysisWindow; threshold: number },
    signal?: AbortSignal,
  ) => post<Evaluation>('/scenario/evaluate', body, signal),
  snap: (waypoints: LonLat[], signal?: AbortSignal) =>
    post<SnapResponse>('/scenario/snap', { waypoints }, signal),
};

/**
 * Live evaluation of a scenario against the baseline. `key` is the scenario's stable hash; the
 * previous result stays on screen (`keepPreviousData`) while the next one computes.
 */
export function useEvaluation(
  edits: ScenarioEdit[] | null,
  key: string,
  window: AnalysisWindow,
  threshold: number,
) {
  return useQuery({
    queryKey: ['evaluate', key, window.day, window.start, window.duration, threshold],
    queryFn: ({ signal }) =>
      scenarioApi.evaluate({ scenario: edits ?? [], window, threshold }, signal),
    enabled: !!edits && edits.length > 0,
    staleTime: Infinity,
    gcTime: 10 * 60_000,
    placeholderData: keepPreviousData,
    retry: (n, err) => !(err instanceof ApiError && err.status === 422) && n < 1,
  });
}

/** Street-snapped path through the draft waypoints (null with fewer than two). */
export function useSnap(waypoints: LonLat[]) {
  const key = waypoints.map((p) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`).join(';');
  return useQuery({
    queryKey: ['snap', key],
    queryFn: ({ signal }) => scenarioApi.snap(waypoints, signal),
    enabled: waypoints.length >= 2,
    staleTime: Infinity,
    placeholderData: keepPreviousData,
    retry: false,
  });
}
