import { useMemo } from 'react';
import { useIsochrone } from '@/api/queries';
import type { IsochroneRequest } from '@/api/types';
import { useApp } from '@/app/store';

export const CUTOFFS = [900, 1800, 2700] as const;
export const ISO_WINDOW = 3600;
/** Departure times are snapped so that nearby clicks/times share the server cache. */
export const ISO_SNAP = 900;

export const snapIsoStart = (time: number) => Math.floor(time / ISO_SNAP) * ISO_SNAP;

export function useIsochroneRequest(): IsochroneRequest | null {
  const origin = useApp((s) => s.isoOrigin);
  const start = useApp((s) => s.isoStart);
  const day = useApp((s) => s.day);
  const mode = useApp((s) => s.isoMode);
  return useMemo(
    () =>
      origin
        ? {
            origin: [Math.round(origin[0] * 1e5) / 1e5, Math.round(origin[1] * 1e5) / 1e5],
            window: { day, start, duration: ISO_WINDOW },
            cutoffs: [...CUTOFFS],
            scenario: null,
            mode,
          }
        : null,
    [origin, start, day, mode],
  );
}

export function useIsochroneResult() {
  const req = useIsochroneRequest();
  const q = useIsochrone(req);
  // keepPreviousData: show the previous result while the next one loads (crossfade)
  return { req, query: q, data: req ? q.data : undefined };
}
