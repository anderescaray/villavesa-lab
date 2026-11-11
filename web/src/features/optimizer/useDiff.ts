import { useMemo } from 'react';
import { useNetwork } from '@/api/queries';
import { useEvaluation, type ScenarioEdit } from '@/api/scenario';
import type { Edit, Evaluation, Network } from '@/api/types';
import { useApp } from '@/app/store';
import { buildNetworkModel, type NetworkModel } from '@/features/network/model';
import { scenarioHash } from '@/features/scenario/store';
import { THRESHOLD, previewedPoint, useOptimizer } from './store';

export interface DiffSource {
  /** the proposal being shown on the map (result of the optimizer or a trade-off point) */
  scenario: Edit[];
  evaluation: Evaluation | null;
  /** proposal network and today's, for lines and stops */
  proposal: NetworkModel | null;
  today: Network | null;
  loading: boolean;
  /** what is shown: the optimizer result or a point of the curve */
  from: 'result' | 'point';
  budget: number | null;
}

/** The proposal to draw: the last optimizer result, or the scenario of a previewed curve point. */
export function useDiff(enabled = true): DiffSource | null {
  const last = useOptimizer((s) => s.last);
  const point = useOptimizer(previewedPoint);
  const day = useApp((s) => s.day);
  const scenario: Edit[] | null = point ? point.scenario : (last?.result.scenario ?? null);
  const window = point ? useOptimizer.getState().tradeoff?.window : last?.window;
  const key = useMemo(
    () => (scenario ? scenarioHash(scenario as ScenarioEdit[]) : 'none'),
    [scenario],
  );
  const evalQ = useEvaluation(
    point && window && scenario?.length && enabled ? (scenario as ScenarioEdit[]) : null,
    key,
    window ?? { day, start: 8 * 3600, duration: 3600 },
    THRESHOLD,
  );
  const todayQ = useNetwork(window?.day ?? day, null);
  const proposalQ = useNetwork(window?.day ?? day, enabled && scenario?.length ? scenario : null);
  const proposal = useMemo(
    () => (proposalQ.data ? buildNetworkModel(proposalQ.data) : null),
    [proposalQ.data],
  );
  if (!scenario) return null;
  const evaluation = point ? (evalQ.data ?? null) : (last?.result.evaluation ?? null);
  return {
    scenario,
    evaluation,
    proposal,
    today: todayQ.data ?? null,
    loading: proposalQ.isFetching || (!!point && evalQ.isFetching),
    from: point ? 'point' : 'result',
    budget: point ? point.budget : null,
  };
}
