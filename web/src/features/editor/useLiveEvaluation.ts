import { useEffect, useMemo, useState } from 'react';
import { useEvaluation } from '@/api/scenario';
import type { AnalysisWindow } from '@/api/types';
import { useApp } from '@/app/store';
import { scenarioHash, useScenario } from '@/features/scenario/store';
import { useEditor } from './state';

export const EVAL_DEBOUNCE_MS = 300;
export const EVAL_WINDOW_S = 3600;
/** analysis windows offered in the impact panel (start, s) */
export const EVAL_WINDOWS = [8 * 3600, 13 * 3600, 18 * 3600] as const;

/**
 * Live diff of the working scenario vs. the baseline. The edit list is debounced (300 ms) so a
 * slider drag only evaluates where the user settles; the previous numbers stay visible (and are
 * flagged `stale`) while the next result computes. Results are cached by the scenario hash.
 */
export function useLiveEvaluation() {
  const edits = useScenario((s) => s.edits);
  const day = useApp((s) => s.day);
  const threshold = useApp((s) => s.accThreshold);
  const start = useEditor((s) => s.windowStart);
  const [debounced, setDebounced] = useState(edits);
  useEffect(() => {
    if (debounced === edits) return;
    const id = window.setTimeout(() => setDebounced(edits), EVAL_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [edits, debounced]);
  const key = useMemo(() => scenarioHash(debounced), [debounced]);
  const win = useMemo<AnalysisWindow>(
    () => ({ day, start, duration: EVAL_WINDOW_S }),
    [day, start],
  );
  const query = useEvaluation(debounced.length ? debounced : null, key, win, threshold);
  const pending = debounced !== edits;
  const hasEdits = edits.length > 0;
  const data = hasEdits ? query.data : undefined;
  const stale = !!data && (pending || (query.isFetching && query.isPlaceholderData));
  return {
    data,
    query,
    stale,
    computing: hasEdits && (pending || query.isFetching),
    error: hasEdits && query.isError && !query.isFetching && !pending ? query.error : null,
    threshold,
    window: win,
  };
}
