import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from './client';
import type { DayType, IsochroneRequest, Scenario } from './types';

/** Stable cache key for a scenario (by value; the server hashes the canonical list too). */
export const scenarioKey = (s: Scenario) => (s && s.length ? JSON.stringify(s) : 'baseline');

export const queryKeys = {
  meta: ['meta'] as const,
  network: (day: DayType, scenario: Scenario) => ['network', day, scenarioKey(scenario)] as const,
  vehicles: (day: DayType, scenario: Scenario) => ['vehicles', day, scenarioKey(scenario)] as const,
  isochrone: (req: IsochroneRequest) => ['isochrone', JSON.stringify(req)] as const,
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
