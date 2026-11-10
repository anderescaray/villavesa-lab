/**
 * The only module that talks HTTP. Every endpoint of docs/api.md the UI uses goes through here,
 * so switching from the mock to the real backend is a no-op.
 */
import type {
  Health,
  IsochroneRequest,
  IsochroneResponse,
  Meta,
  Network,
  NetworkRequest,
  Poi,
  Vehicles,
  VehiclesRequest,
} from './types';

const BASE = '/api';

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function extraHeaders(): Record<string, string> {
  // Dev-only failure injection for the mock API (designing error states): add ?mock_fail=1.
  if (import.meta.env.DEV && typeof window !== 'undefined') {
    const q = window.location.hash.split('?')[1] ?? '';
    if (new URLSearchParams(q).get('mock_fail') === '1') return { 'x-mock-fail': '1' };
  }
  return {};
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...extraHeaders(),
        ...init.headers,
      },
    });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError(0, 'network');
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const post = <T>(path: string, body: unknown, signal?: AbortSignal) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body), signal });

export const api = {
  health: (signal?: AbortSignal) => request<Health>('/health', { signal }),
  meta: (signal?: AbortSignal) => request<Meta>('/meta', { signal }),
  network: (body: NetworkRequest, signal?: AbortSignal) =>
    body.scenario && body.scenario.length
      ? post<Network>('/network', body, signal)
      : request<Network>(`/network?day=${encodeURIComponent(body.day)}`, { signal }),
  vehicles: (body: VehiclesRequest, signal?: AbortSignal) =>
    post<Vehicles>('/vehicles', body, signal),
  isochrone: (body: IsochroneRequest, signal?: AbortSignal) =>
    post<IsochroneResponse>('/isochrone', body, signal),
  pois: (signal?: AbortSignal) => request<{ pois: Poi[] }>('/pois', { signal }),
};
