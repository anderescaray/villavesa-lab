/** The only module that talks HTTP. Every endpoint of docs/api.md the UI uses goes through here. */
import type {
  Accessibility,
  AccessibilityRequest,
  Health,
  IsochroneRequest,
  IsochroneResponse,
  Meta,
  Network,
  NetworkRequest,
  Poi,
  ZonesGeoJSON,
  SectionsGeoJSON,
  Vehicles,
  VehiclesRequest,
} from './types';

const BASE = '/api';

/** The engine is still starting (proxy or API not ready): callers retry quietly. */
export const isEngineLoading = (err: unknown) =>
  err instanceof ApiError && [0, 502, 503, 504].includes(err.status);

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
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
  accessibility: (body: AccessibilityRequest, signal?: AbortSignal) =>
    post<Accessibility>('/accessibility', body, signal),
  zones: (signal?: AbortSignal) => request<ZonesGeoJSON>('/zones', { signal }),
  sections: (signal?: AbortSignal) => request<SectionsGeoJSON>('/sections', { signal }),
  pois: (signal?: AbortSignal) => request<{ pois: Poi[] }>('/pois', { signal }),
};
