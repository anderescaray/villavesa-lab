import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from './client';
import type { AccessibilityRequest, DayType, IsochroneRequest, Scenario } from './types';

/** Stable cache key for a scenario (by value; the server hashes the canonical list too). */
export const scenarioKey = (s: Scenario) => (s && s.length ? JSON.stringify(s) : 'baseline');

export const queryKeys = {
  meta: ['meta'] as const,
  network: (day: DayType, scenario: Scenario) => ['network', day, scenarioKey(scenario)] as const,
  vehicles: (day: DayType, scenario: Scenario) => ['vehicles', day, scenarioKey(scenario)] as const,
  isochrone: (req: IsochroneRequest) => ['isochrone', JSON.stringify(req)] as const,
  accessibility: (req: AccessibilityRequest) =>
    [
      'accessibility',
      req.window.day,
      req.window.start,
      req.window.duration,
      req.threshold,
      scenarioKey(req.scenario),
    ] as const,
  zones: ['zones'] as const,
  pois: ['pois'] as const,
};

export function useMeta() {
  return useQuery({
    queryKey: queryKeys.meta,
    queryFn: ({ signal }) => api.meta(signal),
    staleTime: Infinity,
  });
}

export function useNetwork(day: DayType, scenario: Scenario = null) {
  return useQuery({
    queryKey: queryKeys.network(day, scenario),
    queryFn: ({ signal }) => api.network({ day, scenario }, signal),
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  });
}

export function useVehicles(day: DayType, scenario: Scenario = null) {
  return useQuery({
    queryKey: queryKeys.vehicles(day, scenario),
    queryFn: ({ signal }) => api.vehicles({ day, scenario }, signal),
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  });
}

export function useIsochrone(req: IsochroneRequest | null) {
  return useQuery({
    queryKey: req ? queryKeys.isochrone(req) : ['isochrone', 'none'],
    queryFn: ({ signal }) => api.isochrone(req as IsochroneRequest, signal),
    enabled: req !== null,
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    retry: 1,
  });
}

export function useAccessibilityQuery(req: AccessibilityRequest | null) {
  return useQuery({
    queryKey: req ? queryKeys.accessibility(req) : ['accessibility', 'none'],
    queryFn: ({ signal }) => api.accessibility(req as AccessibilityRequest, signal),
    enabled: req !== null,
    staleTime: Infinity,
    gcTime: 30 * 60_000,
    // keep the previous choropleth (dimmed) while the next window computes
    placeholderData: keepPreviousData,
  });
}

/** Static zone cells (GeoJSON, feature id = zone index). */
export function useZones(enabled = true) {
  return useQuery({
    queryKey: queryKeys.zones,
    queryFn: ({ signal }) => api.zones(signal),
    staleTime: Infinity,
    enabled,
  });
}

export function usePois(enabled = true) {
  return useQuery({
    queryKey: queryKeys.pois,
    queryFn: ({ signal }) => api.pois(signal),
    staleTime: Infinity,
    enabled,
  });
}
