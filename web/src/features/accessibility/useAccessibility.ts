import { useEffect, useMemo, useState } from 'react';
import { useAccessibilityQuery } from '@/api/queries';
import type { AccessibilityRequest } from '@/api/types';
import { useApp } from '@/app/store';
import { useClock } from '@/features/time/clock';

/** Analysis windows start on the half hour and last one hour. */
export const ACC_SNAP = 1800;
export const ACC_WINDOW = 3600;

/** Window start from the clock, snapped to 30 min (re-renders only when the half hour changes). */
export function useWindowStart(): number {
  return useClock((s) => Math.floor(s.time / ACC_SNAP) * ACC_SNAP);
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return v;
}

/**
 * The accessibility analysis for the current day, window and threshold. Scrubbing the clock is
 * debounced so only the window the user settles on is requested.
 */
export function useAccessibility() {
  const view = useApp((s) => s.view);
  const day = useApp((s) => s.day);
  const threshold = useApp((s) => s.accThreshold);
  const liveStart = useWindowStart();
  const start = useDebounced(liveStart, 250);
  const req = useMemo<AccessibilityRequest | null>(
    () =>
      view === 'accessibility'
        ? { window: { day, start, duration: ACC_WINDOW }, threshold, scenario: null }
        : null,
    [view, day, start, threshold],
  );
  const query = useAccessibilityQuery(req);
  const data = query.data;
  // the shown data may be a placeholder for another window while the new one computes
  const stale =
    !!data &&
    !!req &&
    (data.window.day !== req.window.day ||
      data.window.start !== req.window.start ||
      data.threshold !== req.threshold);
  return { req, query, data, stale: stale || (query.isFetching && query.isPlaceholderData) };
}
